# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors


import pytest

from app.services import episode_state, message_format
from app.services.message_models import Kind


async def _seed_episode(client, room: str, short_id: str = "abc123", *, broken: bool = False):
    """A conductor run's record: its intent, a turn to each member and their
    replies, and the commit, each parenting the one before it."""
    await client.post("/api/rooms", json={"name": room})
    episode = message_format.episode_urn(room, short_id)
    topic = message_format.topic_urn(room)
    ep = episode_state.EpisodeState(
        episode=episode,
        topic=topic,
        parent_room=room,
        short_id=short_id,
        workspace_id="ws-1",
        mas_id="mas-1",
        agents=["alice", "bob"],
        engine_handle="conductor",
    )

    def add(**kw) -> str:
        env = message_format.build_envelope(episode=episode, topic=topic, **kw)
        ep.messages.append(message_format.envelope_to_dict(env))
        assert env.header.message is not None
        return env.header.message.id

    last = add(kind=Kind.intent, subkind="mission", sender="conductor", payload_type="intent")
    replies: list[str] = []
    for handle in ("alice", "bob"):
        turn = add(
            kind=Kind.exchange,
            parents=[last],
            sender="conductor",
            recipients=[handle],
            payload_type="message",
        )
        replies.append(
            add(
                kind=Kind.exchange,
                parents=[turn],
                sender=handle,
                sender_role="agent",
                payload_type="reply",
            )
        )
    metrics = {"satisfaction": {"alice": 0.9, "bob": 0.8}, "min_satisfaction": 0.8}
    outcome = "rejected" if broken else "converged"
    add(
        kind=Kind.commit,
        subkind=outcome,
        parents=replies,
        sender="conductor",
        recipients=["alice", "bob"],
        payload_type="outcome",
        payload_data={"metrics": metrics},
    )
    episode_state.write_episode_record(ep, outcome=outcome, metrics=metrics)
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
    assert summary["tasks"] == []
    assert summary["message_count"] > 0
    # Metrics are lifted straight off the commit envelope, not the markdown.
    assert summary["metrics"]["satisfaction"] == metrics["satisfaction"]
    assert summary["metrics"]["min_satisfaction"] == metrics["min_satisfaction"]


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
    assert messages, "expected the full message chain"
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


# ── an episode that carries its flow ─────────────────────────────────────────


def _flow_record(outcome: str, trace: list[dict], *, within: str | None = None) -> str:
    from app.services import episode_state

    ep = episode_state.EpisodeState(
        episode="urn:ioc:mycelium:episode:r:e1",
        topic="urn:concept:mycelium:r",
        parent_room="r",
        short_id="e1",
        workspace_id="ws",
        mas_id="",
        agents=["api", "sec"],
        engine_handle="conductor",
        flow={
            "name": "gated",
            "roles": ["proposer", "guardian"],
            "steps": [
                {"id": "propose", "to": "proposer", "next": "review"},
                {
                    "id": "review",
                    "to": "guardian",
                    "next": {"accept": "approved", "reject": "propose"},
                },
                {"id": "approved", "end": "resolved"},
            ],
            "bound": {"proposer": "api", "guardian": "sec"},
        },
        trace=trace,
        within=within,
    )
    ep.messages.append(
        {
            "header": {
                "kind": "commit" if outcome != "open" else "intent",
                "subkind": outcome if outcome != "open" else "mission",
                "message": {"id": "m1", "episode": ep.episode},
                "context": {"topic": ep.topic},
                "participants": {"actors": [{"id": "conductor", "role": "agent"}]},
            },
            "payload": {"type": "outcome", "data": {}},
        }
    )
    episode_state.write_episode_record(ep, outcome=outcome, metrics=None)
    return f"log/episodes/{ep.short_id}"


def test_a_flow_record_reads_back_its_graph_trace_and_parent(tmp_path, monkeypatch):
    from app.services.episode_records import episode_summary
    from app.services.filesystem import get_room_dir, read_memory_file

    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    get_room_dir("r")
    trace = [
        {
            "step": "propose",
            "turn": 1,
            "asked": ["api"],
            "stances": {"api": None},
            "stance": None,
            "next": "review",
        }
    ]
    key = _flow_record("open", trace, within="urn:ioc:mycelium:episode:r:t3")

    found = read_memory_file(get_room_dir("r"), key)
    assert found is not None
    summary = episode_summary(key, *found)
    assert summary["outcome"] == "open"
    assert summary["within"] == "urn:ioc:mycelium:episode:r:t3"
    assert summary["flow"]["name"] == "gated"
    assert summary["flow"]["bound"] == {"proposer": "api", "guardian": "sec"}
    assert summary["trace"] == trace
    assert summary["current_step"] == "review", "the step the last trace entry led to"


def test_an_open_flow_with_no_steps_yet_stands_at_its_first(tmp_path, monkeypatch, caplog):
    from app.services.episode_records import episode_summary
    from app.services.filesystem import get_room_dir, read_memory_file

    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    get_room_dir("r")
    key = _flow_record("open", [])
    found = read_memory_file(get_room_dir("r"), key)
    assert found is not None
    with caplog.at_level("WARNING"):
        summary = episode_summary(key, *found)
    assert summary["current_step"] == "propose"
    assert summary["within"] is None
    # An empty Trace fence is an empty trace: it must not run on into the
    # Messages block, which would log a malformed line per envelope there and
    # hide the one message the record does carry.
    assert summary["trace"] == []
    assert summary["participants"] == ["conductor"]
    assert "malformed" not in caplog.text


def test_a_finished_flow_stands_nowhere_and_a_negotiation_has_no_flow(tmp_path, monkeypatch):
    from app.services.episode_records import episode_summary
    from app.services.filesystem import get_room_dir, read_memory_file

    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    get_room_dir("r")
    key = _flow_record("resolved", [{"step": "review", "turn": 2, "next": "approved"}])
    found = read_memory_file(get_room_dir("r"), key)
    assert found is not None
    summary = episode_summary(key, *found)
    assert summary["current_step"] is None
    assert summary["outcome"] == "resolved"

    plain = "# Episode x\n\n## Messages\n\n```jsonl\n\n```\n"
    summary = episode_summary("log/episodes/x", {}, plain)
    assert summary["flow"] is None
    assert summary["trace"] == []
    assert summary["within"] is None
