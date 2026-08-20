# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors


import pytest

from app.services import l9_episode


async def _seed_episode(client, room: str, short_id: str = "abc123", *, broken: bool = False):
    await client.post("/api/rooms", json={"name": room})
    ep = l9_episode.open_episode(
        parent_room=room,
        short_id=short_id,
        workspace_id="ws-1",
        mas_id="mas-1",
        agents=["alice", "bob"],
        joined_intents="- alice: ship it\n- bob: test it",
    )
    for handle in ("alice", "bob"):
        l9_episode.record_tick(ep, handle=handle, round_n=1, payload={"action": "respond"})
        l9_episode.record_reply(
            ep,
            handle=handle,
            reply={"action": "accept", "confidence": 0.9, "issue": "value"},
            round_n=1,
        )
    metrics = l9_episode.compute_metrics(ep)
    l9_episode.build_consensus_envelope(
        ep, broken=broken, assignments={"issue": "value"}, metrics=metrics
    )
    l9_episode.write_episode_record(
        ep,
        outcome="rejected" if broken else "converged",
        metrics=metrics,
        plan_file="plan/tasks.md",
    )
    return ep, metrics


@pytest.mark.asyncio
async def test_list_episodes_returns_summary(client):
    _ep, metrics = await _seed_episode(client, "sprint")

    resp = await client.get("/api/rooms/sprint/episodes")
    assert resp.status_code == 200
    episodes = resp.json()["episodes"]
    assert len(episodes) == 1
    summary = episodes[0]
    assert summary["short_id"] == "abc123"
    assert summary["episode"] == "urn:ioc:mycelium:episode:sprint:abc123"
    assert summary["outcome"] == "converged"
    assert summary["subkind"] == "converged"
    assert summary["participants"] == ["alice", "bob"]
    assert summary["plan_file"] == "plan/tasks.md"
    assert summary["message_count"] > 0
    # Metrics are lifted straight off the commit envelope, not the markdown.
    assert summary["metrics"]["mpc"] == metrics["mpc"]
    assert summary["metrics"]["gar"] == metrics["gar"]


@pytest.mark.asyncio
async def test_list_episodes_surfaces_an_in_progress_episode(client):
    from app.services.room_channels import ManagedRoomChannel, manager

    room = "live-room"
    await client.post("/api/rooms", json={"name": room})
    urn = "urn:ioc:mycelium:episode:live-room:aa11bb22"
    managed = ManagedRoomChannel(room=room, workspace="ws-1", client=None, channel=None)  # type: ignore[arg-type]
    managed.lifecycle.open(urn, {"alice", "bob", "backend"})
    manager._channels[room] = managed
    try:
        resp = await client.get("/api/rooms/live-room/episodes")
        assert resp.status_code == 200
        episodes = resp.json()["episodes"]
        assert len(episodes) == 1
        live = episodes[0]
        assert live["short_id"] == "aa11bb22"
        assert live["episode"] == urn
        assert live["outcome"] == "open"
        assert live["participants"] == ["alice", "bob"]  # backend moderator dropped
    finally:
        manager._channels.pop(room, None)


@pytest.mark.asyncio
async def test_get_episode_returns_causal_chain(client):
    await _seed_episode(client, "sprint")

    resp = await client.get("/api/rooms/sprint/episodes/abc123")
    assert resp.status_code == 200
    episode = resp.json()

    messages = episode["messages"]
    assert messages, "expected the full L9 envelope chain"
    kinds = [m["header"]["kind"] for m in messages]
    assert kinds[0] == "intent"
    assert "exchange" in kinds
    assert kinds[-1] == "commit"

    # Causality is threaded: the commit parents the final replies.
    commit = messages[-1]
    assert commit["header"]["subkind"] == "converged"
    assert commit["header"]["message"]["parents"], "commit must name its causal parents"


@pytest.mark.asyncio
async def test_episode_envelopes_carry_actor_identity(client):
    """Every envelope carries its sender as the first participant, with no flattened `sender_handle` on the wire."""
    await _seed_episode(client, "sprint")

    resp = await client.get("/api/rooms/sprint/episodes/abc123")
    assert resp.status_code == 200
    messages = resp.json()["messages"]

    # An exchange tick/reply names a concrete agent as its first actor.
    exchanges = [m for m in messages if m["header"]["kind"] == "exchange"]
    assert exchanges, "expected exchange envelopes in the chain"
    for env in exchanges:
        actors = env["header"]["participants"]["actors"]
        assert actors, "every exchange must name its participant actors"
        assert actors[0]["id"], "the first actor is the sender handle the UI renders"
        assert "sender_handle" not in env

    # An agent reply resolves to a real handle (not the system actor).
    senders = {m["header"]["participants"]["actors"][0]["id"] for m in exchanges}
    assert senders & {"alice", "bob"}, "agent replies surface the agent's handle"


@pytest.mark.asyncio
async def test_rejected_episode_reports_rejected_outcome(client):
    await _seed_episode(client, "sprint", short_id="deadxx", broken=True)

    resp = await client.get("/api/rooms/sprint/episodes/deadxx")
    assert resp.status_code == 200
    assert resp.json()["subkind"] == "rejected"


@pytest.mark.asyncio
async def test_episodes_unknown_room_is_404(client):
    resp = await client.get("/api/rooms/nope/episodes")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_episode_is_404(client):
    await client.post("/api/rooms", json={"name": "sprint"})
    resp = await client.get("/api/rooms/sprint/episodes/missing")
    assert resp.status_code == 404
