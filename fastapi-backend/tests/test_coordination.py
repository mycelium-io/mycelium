# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Unit tests for app.services.coordination.

Mocks:
- app.services.cfn_negotiation.start_negotiation / decide_negotiation (no HTTP)
- app.services.coordination.async_session_maker (no DB)
- app.services.coordination.notify / asyncpg.connect (no Postgres NOTIFY)
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import coordination as coord
from app.services.coordination import (
    _cfn_decide_round,
    _cfn_state,
    _CfnRoundState,
    _fan_out_cfn_messages,
    on_agent_response,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_broadcast_msg(round_num: int = 1, next_proposer: str = "alice") -> dict:
    """Build a minimal BatchCallbackRunner-style broadcast SSTPNegotiateMessage dict."""
    return {
        "kind": "negotiate",
        "message_id": f"msg-{round_num}",
        "semantic_context": {
            "session_id": "test-session",
            "issues": ["price", "timeline"],
            "options_per_issue": {
                "price": ["low", "mid", "high"],
                "timeline": ["6mo", "12mo"],
            },
        },
        "payload": {
            "participant_id": "server",  # broadcast
            "action": "respond",
            "round": round_num,
            "allowed_actions": ["accept", "reject", "counter_offer"],
            "current_offer": {"price": "mid", "timeline": "12mo"},
            "proposer_id": "server",
            "next_proposer_id": next_proposer,
        },
    }


def _make_room(room_name: str = "test-room", mas_id: str = "mas-1", workspace_id: str = "ws-1"):
    room = MagicMock()
    room.name = room_name
    room.mas_id = mas_id
    room.workspace_id = workspace_id
    room.parent_namespace = None
    return room


def _patch_db():
    """Return a context manager that stubs async_session_maker to a no-op."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    msg = MagicMock()
    msg.id = 1
    msg.created_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_session.add.side_effect = lambda m: setattr(m, "id", 1) or setattr(
        m, "created_at", MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
    )

    return patch("app.services.coordination.async_session_maker", return_value=mock_session)


def _patch_notify():
    """Stub out asyncpg connect + notify so _post_message doesn't need Postgres."""
    mock_conn = AsyncMock()
    return (
        patch("app.services.coordination.asyncpg.connect", AsyncMock(return_value=mock_conn)),
        patch("app.services.coordination.notify", AsyncMock()),
    )


# ── Tests: _fan_out_cfn_messages ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fan_out_broadcast_sends_tick_to_all_agents():
    """A broadcast message fans out one tick per agent."""
    posted = []

    async def fake_post(room_name, message_type, content):
        posted.append((message_type, json.loads(content)))

    with patch.object(coord, "_post_message", side_effect=fake_post):
        agents = ["alice", "bob"]
        msg = _make_broadcast_msg(round_num=1, next_proposer="alice")
        addressed = await _fan_out_cfn_messages("room", [msg], all_agents=agents)

    assert addressed == ["alice", "bob"]
    assert len(posted) == 2
    types = [p[0] for p in posted]
    assert all(t == "coordination_tick" for t in types)

    alice_tick = next(p[1] for p in posted if p[1]["payload"]["participant_id"] == "alice")
    bob_tick = next(p[1] for p in posted if p[1]["payload"]["participant_id"] == "bob")

    assert alice_tick["payload"]["can_counter_offer"] is True  # alice is next_proposer
    assert bob_tick["payload"]["can_counter_offer"] is False
    assert alice_tick["payload"]["round"] == 1
    assert alice_tick["payload"]["issues"] == ["price", "timeline"]


@pytest.mark.asyncio
async def test_fan_out_no_agents_returns_empty():
    """Without all_agents, broadcast produces nothing."""
    msg = _make_broadcast_msg()
    addressed = await _fan_out_cfn_messages("room", [msg], all_agents=None)
    assert addressed == []


@pytest.mark.asyncio
async def test_fan_out_uses_parent_issues_when_sc_missing():
    """Falls back to parent_issues/options when semantic_context is absent."""
    posted = []

    async def fake_post(room_name, message_type, content):
        posted.append(json.loads(content))

    msg = _make_broadcast_msg()
    msg["semantic_context"] = {}  # no issues in sc

    with patch.object(coord, "_post_message", side_effect=fake_post):
        await _fan_out_cfn_messages(
            "room",
            [msg],
            all_agents=["alice"],
            parent_issues=["budget"],
            parent_options_per_issue={"budget": ["a", "b"]},
        )

    assert posted[0]["payload"]["issues"] == ["budget"]


# ── Tests: session_id uniqueness ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cfn_state_keyed_by_room_name_not_mas_id():
    """Two session rooms sharing a mas_id must create independent CFN states."""
    _cfn_state.clear()

    room1 = _make_room("ns:session:aaa", mas_id="shared-mas")
    room2 = _make_room("ns:session:bbb", mas_id="shared-mas")

    posted_msgs = []

    async def fake_post(room_name, message_type, content):
        posted_msgs.append((room_name, message_type, content))

    start_response = {
        "status": "initiated",
        "messages": [_make_broadcast_msg(round_num=1, next_proposer="alice")],
        "issues": ["price"],
        "options_per_issue": {"price": ["low", "high"]},
    }

    with (
        patch(
            "app.services.cfn_negotiation.start_negotiation", AsyncMock(return_value=start_response)
        ),
        patch.object(coord, "_post_message", side_effect=fake_post),
        patch.object(coord, "async_session_maker"),
    ):
        await coord._run_cfn_negotiation(
            "ns:session:aaa", room1, ["alice", "bob"], ["buy house", "sell house"]
        )
        await coord._run_cfn_negotiation(
            "ns:session:bbb", room2, ["carol", "dave"], ["buy car", "sell car"]
        )

    assert "ns:session:aaa" in _cfn_state
    assert "ns:session:bbb" in _cfn_state
    # session_ids must differ even though mas_id is the same
    assert _cfn_state["ns:session:aaa"].session_id != _cfn_state["ns:session:bbb"].session_id
    assert _cfn_state["ns:session:aaa"].session_id == "ns:session:aaa"
    assert _cfn_state["ns:session:bbb"].session_id == "ns:session:bbb"

    _cfn_state.clear()


# ── Tests: double-decide guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_double_decide_guard_prevents_concurrent_calls():
    """If deciding=True, a second call to _cfn_decide_round is a no-op."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-x",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
        deciding=True,  # already deciding
    )
    _cfn_state["room-x"] = state

    decide_calls = []

    async def fake_decide(**kwargs):
        decide_calls.append(kwargs)
        return {}

    with patch("app.services.cfn_negotiation.decide_negotiation", side_effect=fake_decide):
        await _cfn_decide_round("room-x")

    assert decide_calls == [], "decide_negotiation should not be called when deciding=True"
    _cfn_state.clear()


@pytest.mark.asyncio
async def test_decide_sets_deciding_false_after_ongoing_round():
    """deciding flag is reset to False after an ongoing round fans out the next tick."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-y",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={
            "alice": {"agent_id": "alice", "action": "reject"},
            "bob": {"agent_id": "bob", "action": "reject"},
        },
    )
    _cfn_state["room-y"] = state

    next_msg = _make_broadcast_msg(round_num=2, next_proposer="bob")
    decide_response = {
        "status": "ongoing",
        "session_id": "room-y",
        "round": 2,
        "messages": [next_msg],
    }

    async def fake_post(room_name, message_type, content):
        pass

    with (
        patch(
            "app.services.cfn_negotiation.decide_negotiation",
            AsyncMock(return_value=decide_response),
        ),
        patch.object(coord, "_post_message", AsyncMock(side_effect=fake_post)),
        patch.object(coord, "_reset_round_timeout"),
    ):
        await _cfn_decide_round("room-y")

    assert _cfn_state.get("room-y") is not None
    assert _cfn_state["room-y"].deciding is False
    _cfn_state.clear()


# ── Tests: on_agent_response ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_agent_response_triggers_decide_when_all_replied():
    """All agents replying triggers _cfn_decide_round."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-z",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
    )
    _cfn_state["room-z"] = state

    decide_called = []

    async def fake_decide(room_name):
        decide_called.append(room_name)

    with patch.object(coord, "_cfn_decide_round", side_effect=fake_decide):
        await on_agent_response("room-z", "alice", json.dumps({"action": "reject"}))
        assert decide_called == [], "only one reply so far — should not decide yet"

        await on_agent_response("room-z", "bob", json.dumps({"action": "accept"}))
        await asyncio.sleep(0)  # let ensure_future run
        assert decide_called == ["room-z"]

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_on_agent_response_ignores_unknown_handle():
    """Replies from handles not in pending_replies are silently ignored."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-w",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _cfn_state["room-w"] = state

    with patch.object(coord, "_cfn_decide_round", AsyncMock()) as mock_decide:
        await on_agent_response("room-w", "eve", json.dumps({"action": "accept"}))
        assert mock_decide.call_count == 0
        assert _cfn_state["room-w"].pending_replies["alice"] is None

    _cfn_state.clear()


# ── Tests: agreement parsing ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agreed_status_parses_semantic_context_final_agreement():
    """Agreement extracted from SSTPCommitMessage.semantic_context.final_agreement."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-a",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": {"agent_id": "alice", "action": "accept"}},
    )
    _cfn_state["room-a"] = state

    commit = {
        "kind": "commit",
        "semantic_context": {
            "session_id": "room-a",
            "final_agreement": [
                {"issue_id": "price", "chosen_option": "mid"},
                {"issue_id": "timeline", "chosen_option": "12mo"},
            ],
        },
        "payload": {"status": "agreed"},
    }
    decide_response = {
        "status": "agreed",
        "session_id": "room-a",
        "round": 3,
        "final_result": commit,
    }

    posted = []

    async def fake_post(room_name, message_type, content):
        posted.append((message_type, json.loads(content)))

    with (
        patch(
            "app.services.cfn_negotiation.decide_negotiation",
            AsyncMock(return_value=decide_response),
        ),
        patch.object(coord, "_post_message", side_effect=fake_post),
        patch.object(coord, "async_session_maker"),
    ):
        await _cfn_decide_round("room-a")

    consensus = next((p[1] for p in posted if p[0] == "coordination_consensus"), None)
    assert consensus is not None
    assert consensus["broken"] is False
    assert consensus["assignments"] == {"price": "mid", "timeline": "12mo"}
    assert "price=mid" in consensus["plan"]

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_timeout_status_posts_broken_consensus():
    """CFN status=timeout results in a broken consensus message."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-b",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _cfn_state["room-b"] = state

    decide_response = {"status": "timeout", "session_id": "room-b", "round": 20}

    posted = []

    async def fake_post(room_name, message_type, content):
        posted.append((message_type, json.loads(content)))

    with (
        patch(
            "app.services.cfn_negotiation.decide_negotiation",
            AsyncMock(return_value=decide_response),
        ),
        patch.object(coord, "_post_message", side_effect=fake_post),
        patch.object(coord, "async_session_maker"),
    ):
        await _cfn_decide_round("room-b")

    consensus = next((p[1] for p in posted if p[0] == "coordination_consensus"), None)
    assert consensus is not None
    assert consensus["broken"] is True

    _cfn_state.clear()


# ── teardown_for_namespace ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_teardown_cancels_pending_join_timer():
    """A pending start_join_timer task should be cancelled, not allowed to run."""
    from datetime import timedelta

    fired = asyncio.Event()

    async def slow_run_tick(_room: str, tick: int) -> None:  # noqa: ARG001
        fired.set()

    with patch.object(coord, "_run_tick", new=AsyncMock(side_effect=slow_run_tick)):
        deadline = coord._utcnow() + timedelta(seconds=10)
        task = coord.schedule_join_timer("ns-a", deadline)
        assert "ns-a" in coord._join_timer_tasks

        # Tear down before the timer fires.
        await coord.teardown_for_namespace("ns-a", [])

        # Task should be cancelled and removed from registry.
        await asyncio.sleep(0.05)
        assert task.cancelled() or task.done()
        assert "ns-a" not in coord._join_timer_tasks
        assert not fired.is_set()


@pytest.mark.asyncio
async def test_teardown_cancels_round_timeout_and_pops_state():
    """Active CFN round state must be removed and its watchdog cancelled."""
    # Build a never-ending round_timeout_task to simulate an in-flight round.
    async def never() -> None:
        await asyncio.sleep(3600)

    timeout_task = asyncio.ensure_future(never())
    state = _CfnRoundState(
        session_id="sess",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
    )
    state.round_timeout_task = timeout_task
    _cfn_state["ns-b:session:1"] = state

    with patch.object(coord, "_post_message", new=AsyncMock()) as post:
        await coord.teardown_for_namespace("ns-b", ["ns-b:session:1"])

    assert "ns-b:session:1" not in _cfn_state
    await asyncio.sleep(0)
    assert timeout_task.cancelled()

    # An abort consensus message should have been posted to the child room
    # (the only room that had active CFN state).
    assert post.call_count == 1
    call = post.call_args_list[0]
    assert call.args[0] == "ns-b:session:1"
    assert call.kwargs["message_type"] == "coordination_consensus"
    body = json.loads(call.kwargs["content"])
    assert body["broken"] is True
    assert body["assignments"] == {}


@pytest.mark.asyncio
async def test_teardown_skips_post_for_rooms_without_cfn_state():
    """Rooms that never started negotiating should NOT receive an abort consensus."""
    # No state for this namespace at all.
    with patch.object(coord, "_post_message", new=AsyncMock()) as post:
        await coord.teardown_for_namespace("ns-c", ["ns-c:session:x"])

    assert post.call_count == 0


@pytest.mark.asyncio
async def test_teardown_handles_post_message_exceptions_gracefully():
    """A broken _post_message call must not propagate; teardown still completes."""
    state = _CfnRoundState(
        session_id="sess",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _cfn_state["ns-d"] = state

    async def boom(*_args, **_kwargs):
        raise RuntimeError("simulated post failure")

    with patch.object(coord, "_post_message", new=AsyncMock(side_effect=boom)):
        # Must not raise.
        await coord.teardown_for_namespace("ns-d", [])

    assert "ns-d" not in _cfn_state


@pytest.mark.asyncio
async def test_schedule_join_timer_clears_registry_on_completion():
    """When the timer task completes naturally, the registry slot is cleared."""
    with patch.object(coord, "_run_tick", new=AsyncMock()):
        deadline = coord._utcnow()  # already passed → run_tick fires immediately
        task = coord.schedule_join_timer("ns-e", deadline)
        await task
        # Allow the done-callback to run.
        await asyncio.sleep(0)
        assert "ns-e" not in coord._join_timer_tasks
