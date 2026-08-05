# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the L9 episode read API that backs the protocol inspector (Step 10)."""

import pytest

from app.services import l9_episode


async def _seed_episode(client, room: str, short_id: str = "abc123", *, broken: bool = False):
    """Create a room and write one closed episode record into its memory."""
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
