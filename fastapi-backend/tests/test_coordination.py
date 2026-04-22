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


# ── Tests: adaptive round watchdog (issue #162) ───────────────────────────────


def test_initial_round_budget_scales_with_n():
    """Initial budget = STARTUP + BASE * N, capped at MAX_ROUND_SECONDS."""
    from app.config import settings
    from app.services.coordination import _initial_round_budget_seconds

    base = settings.COORDINATION_TICK_TIMEOUT_SECONDS
    startup = settings.COORDINATION_ROUND_STARTUP_SECONDS
    cap = settings.COORDINATION_ROUND_MAX_SECONDS

    # 1 agent → at least startup + base, well under the cap
    assert _initial_round_budget_seconds(1) == min(cap, startup + base)
    # 3 agents → scales linearly
    assert _initial_round_budget_seconds(3) == min(cap, startup + 3 * base)
    # Pathologically large N is clamped at the cap
    assert _initial_round_budget_seconds(10_000) == cap
    # Defensive: 0 / negative N treated as 1
    assert _initial_round_budget_seconds(0) == _initial_round_budget_seconds(1)


def test_extension_seconds_floor_and_scaling():
    """Extension = max(FLOOR, PER_REMAINING * remaining); never below FLOOR."""
    from app.config import settings
    from app.services.coordination import _extension_seconds

    per = settings.COORDINATION_ROUND_EXTENSION_PER_REMAINING_SECONDS
    floor = settings.COORDINATION_ROUND_EXTENSION_FLOOR_SECONDS

    assert _extension_seconds(1) == max(floor, per * 1)
    assert _extension_seconds(5) == max(floor, per * 5)
    # Defensive: 0 remaining still returns at least the floor
    assert _extension_seconds(0) >= floor


@pytest.mark.asyncio
async def test_extend_round_timeout_restarts_with_shorter_window():
    """A new real reply mid-round should restart the watchdog at extension delay,
    not the full initial budget — proves we stop firing the 25s default."""
    from app.services.coordination import _extend_round_timeout, _reset_round_timeout

    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-ext",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob", "carol"],
        pending_replies={"alice": None, "bob": None, "carol": None},
    )
    _cfn_state["room-ext"] = state

    # Open the round normally — schedules a long initial watchdog.
    _reset_round_timeout("room-ext", state)
    initial_task = state.round_timeout_task
    assert initial_task is not None and not initial_task.done()

    # Simulate alice replying.
    state.pending_replies["alice"] = {"agent_id": "alice", "action": "accept"}
    _extend_round_timeout("room-ext", state)

    # Yield once so the cancellation requested by _extend_round_timeout has a
    # chance to settle (cancel() puts the task in CANCELLING, the next loop
    # iteration completes the transition to CANCELLED).
    try:
        await initial_task
    except asyncio.CancelledError:
        pass

    assert initial_task.cancelled() or initial_task.done()
    assert state.round_timeout_task is not initial_task
    assert state.round_timeout_task is not None and not state.round_timeout_task.done()

    # Cleanup: cancel the new task to avoid leaking a sleep into the test loop.
    state.round_timeout_task.cancel()
    try:
        await state.round_timeout_task
    except asyncio.CancelledError:
        pass
    _cfn_state.clear()


@pytest.mark.asyncio
async def test_extend_round_timeout_respects_hard_cap():
    """If we've already burned more than COORDINATION_ROUND_MAX_SECONDS,
    extension is a no-op (the original watchdog is left to fire)."""
    from app.config import settings
    from app.services.coordination import _extend_round_timeout, _reset_round_timeout

    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-cap",
        workspace_id="ws",
        mas_id="mas",
        agents=["a", "b"],
        pending_replies={"a": None, "b": None},
    )
    _cfn_state["room-cap"] = state

    _reset_round_timeout("room-cap", state)
    original_task = state.round_timeout_task

    # Pretend the round opened well in the past so budget_left <= 0.
    state.round_started_monotonic -= settings.COORDINATION_ROUND_MAX_SECONDS + 5

    state.pending_replies["a"] = {"agent_id": "a", "action": "accept"}
    _extend_round_timeout("room-cap", state)

    # No new task scheduled; original watchdog still in place.
    assert state.round_timeout_task is original_task

    # Cleanup
    if original_task is not None and not original_task.done():
        original_task.cancel()
        try:
            await original_task
        except asyncio.CancelledError:
            pass
    _cfn_state.clear()


@pytest.mark.asyncio
async def test_on_agent_response_extends_watchdog_when_partial():
    """A real reply that doesn't complete the round triggers _extend_round_timeout."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-on",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob", "carol"],
        pending_replies={"alice": None, "bob": None, "carol": None},
    )
    _cfn_state["room-on"] = state

    with patch.object(coord, "_extend_round_timeout") as mock_extend:
        await on_agent_response("room-on", "alice", json.dumps({"action": "accept"}))

    mock_extend.assert_called_once_with("room-on", state)
    assert state.pending_replies["alice"]["action"] == "accept"
    _cfn_state.clear()


@pytest.mark.asyncio
async def test_on_agent_response_does_not_extend_when_all_in():
    """The last reply triggers decide, NOT extend — no double-scheduling."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-last",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={
            "alice": {"agent_id": "alice", "action": "accept"},
            "bob": None,
        },
    )
    _cfn_state["room-last"] = state

    with (
        patch.object(coord, "_extend_round_timeout") as mock_extend,
        patch.object(coord, "_cfn_decide_round", AsyncMock()) as mock_decide,
    ):
        await on_agent_response("room-last", "bob", json.dumps({"action": "accept"}))
        # Let the asyncio.ensure_future(_cfn_decide_round) settle.
        await asyncio.sleep(0)

    mock_extend.assert_not_called()
    mock_decide.assert_called_once_with("room-last")
    _cfn_state.clear()


@pytest.mark.asyncio
async def test_on_agent_response_does_not_extend_on_resubmit():
    """If an agent re-sends an already-collected reply, don't keep extending —
    only first-time real replies should restart the watchdog."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-resub",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob", "carol"],
        pending_replies={
            "alice": {"agent_id": "alice", "action": "accept"},  # already replied
            "bob": None,
            "carol": None,
        },
    )
    _cfn_state["room-resub"] = state

    with patch.object(coord, "_extend_round_timeout") as mock_extend:
        await on_agent_response("room-resub", "alice", json.dumps({"action": "accept"}))

    mock_extend.assert_not_called()
    _cfn_state.clear()
