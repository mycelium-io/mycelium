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
    _parse_agent_reply,
    _validate_and_fill_offer,
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
    mock_session.add.side_effect = lambda m: (
        setattr(m, "id", 1)
        or setattr(m, "created_at", MagicMock(isoformat=lambda: "2026-01-01T00:00:00"))
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

    async def fake_decide(room_name, **_kwargs):
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

    async def slow_run_tick(_room: str, tick: int) -> None:
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


# ── Tests: _validate_and_fill_offer / _parse_agent_reply ─────────────────────


def test_validate_and_fill_offer_bad_key_returns_invalid_keys():
    """Keys not in current_offer return the invalid_keys sentinel."""
    current_offer = {"price": "mid", "timeline": "12mo"}
    result = {
        "agent_id": "alice",
        "participant_id": "alice",
        "action": "counter_offer",
        "offer": {"price": "high", "scope": "full"},
    }
    out = _validate_and_fill_offer("alice", result, current_offer)
    assert out["action"] == "invalid_keys"
    assert out["bad_keys"] == ["scope"]
    assert set(out["valid_keys"]) == {"price", "timeline"}


def test_validate_and_fill_offer_case_sensitive():
    """Key matching is case-sensitive — wrong casing produces invalid_keys."""
    current_offer = {"Demo is non-negotiable": "yes"}
    result = {
        "agent_id": "alice",
        "participant_id": "alice",
        "action": "counter_offer",
        "offer": {"demo is non-negotiable": "yes"},
    }
    out = _validate_and_fill_offer("alice", result, current_offer)
    assert out["action"] == "invalid_keys"
    assert out["bad_keys"] == ["demo is non-negotiable"]


def test_validate_and_fill_offer_partial_fill():
    """Valid but partial offer gets silently filled from anchor; agent values win."""
    current_offer = {"price": "mid", "timeline": "12mo", "scope": "standard"}
    result = {
        "agent_id": "alice",
        "participant_id": "alice",
        "action": "counter_offer",
        "offer": {"price": "high"},
    }
    out = _validate_and_fill_offer("alice", result, current_offer)
    assert out["action"] == "counter_offer"
    assert out["offer"] == {"price": "high", "timeline": "12mo", "scope": "standard"}


def test_validate_and_fill_offer_no_current_offer_passthrough():
    """When current_offer is None, the offer is returned unchanged."""
    result = {
        "agent_id": "alice",
        "participant_id": "alice",
        "action": "counter_offer",
        "offer": {"anything": "goes"},
    }
    out = _validate_and_fill_offer("alice", result, None)
    assert out["action"] == "counter_offer"
    assert out["offer"] == {"anything": "goes"}


def test_parse_agent_reply_counter_offer_invalid_key():
    """_parse_agent_reply returns invalid_keys when offer has unrecognised keys."""
    content = json.dumps({"action": "counter_offer", "offer": {"bad_key": "val"}})
    out = _parse_agent_reply("alice", content, current_offer={"price": "mid"})
    assert out["action"] == "invalid_keys"
    assert "bad_key" in out["bad_keys"]


def test_parse_agent_reply_offer_only_format_validates():
    """offer-only JSON also goes through validation."""
    content = json.dumps({"offer": {"wrong": "x"}})
    out = _parse_agent_reply("bob", content, current_offer={"price": "mid"})
    assert out["action"] == "invalid_keys"


# ── Tests: on_agent_response — invalid keys ───────────────────────────────────


@pytest.mark.asyncio
async def test_on_agent_response_invalid_key_posts_corrective_tick():
    """Bad counter-offer key: corrective tick posted, pending_replies stays None."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-v",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
        current_offer={"price": "mid", "timeline": "12mo"},
        issue_options={"price": ["low", "mid", "high"], "timeline": ["6mo", "12mo"]},
    )
    _cfn_state["room-v"] = state

    posted = []

    async def fake_post(room_name, message_type, content):
        posted.append((message_type, json.loads(content)))

    with patch.object(coord, "_post_message", side_effect=fake_post):
        await on_agent_response(
            "room-v", "alice", json.dumps({"action": "counter_offer", "offer": {"typo_key": "x"}})
        )

    # Pending reply must still be None — round is not advanced
    assert _cfn_state["room-v"].pending_replies["alice"] is None

    # Exactly one corrective tick posted
    assert len(posted) == 1
    msg_type, content = posted[0]
    assert msg_type == "coordination_tick"
    assert content["error"] == "counter_offer_invalid_keys"
    assert "typo_key" in content["bad_keys"]
    assert content["payload"]["participant_id"] == "alice"

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_on_agent_response_partial_offer_stored_as_merged():
    """Partial counter-offer is filled from anchor and stored in pending_replies."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-p",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
        current_offer={"price": "mid", "timeline": "12mo"},
        issue_options={"price": ["low", "mid", "high"], "timeline": ["6mo", "12mo"]},
    )
    _cfn_state["room-p"] = state

    decide_called = []

    async def fake_decide(room_name, **_kwargs):
        decide_called.append(room_name)

    with patch.object(coord, "_cfn_decide_round", side_effect=fake_decide):
        await on_agent_response(
            "room-p", "alice", json.dumps({"action": "counter_offer", "offer": {"price": "high"}})
        )
        await asyncio.sleep(0)

    stored = _cfn_state["room-p"].pending_replies["alice"]
    assert stored is not None
    assert stored["offer"]["price"] == "high"
    assert stored["offer"]["timeline"] == "12mo"  # filled from anchor
    assert decide_called == ["room-p"]

    _cfn_state.clear()


# ── Tests: fan_out updates _cfn_state ────────────────────────────────────────


@pytest.mark.asyncio
async def test_fan_out_populates_cfn_state_fields():
    """After fan-out, _cfn_state reflects current_offer, issues, issue_options, round."""
    _cfn_state.clear()

    state = _CfnRoundState(
        session_id="room-fo",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _cfn_state["room-fo"] = state

    async def fake_post(room_name, message_type, content):
        pass

    msg = _make_broadcast_msg(round_num=2, next_proposer="alice")
    with patch.object(coord, "_post_message", side_effect=fake_post):
        await _fan_out_cfn_messages("room-fo", [msg], all_agents=["alice"])

    assert state.current_round == 2
    assert state.current_offer == {"price": "mid", "timeline": "12mo"}
    assert state.issues == ["price", "timeline"]
    assert state.issue_options == {"price": ["low", "mid", "high"], "timeline": ["6mo", "12mo"]}

    _cfn_state.clear()


# ── Tests: round trace instrumentation (#162) ────────────────────────────────
#
# These are CI-safe (no real CFN, no real DB) — they exercise the in-memory
# trace machinery directly using the same mocking pattern as the rest of this
# file.  Companion E2E coverage that scrapes
# /api/internal/coordination/round-traces against a live backend lives outside
# this repository in the operator test harness.


@pytest.fixture(autouse=False)
def clean_trace_buffer():
    """Snapshot/restore the trace buffer so trace tests don't leak into each other."""
    coord.clear_round_traces()
    yield
    coord.clear_round_traces()


def _attach_trace(state: _CfnRoundState, room_name: str, addressed: list[str]) -> None:
    """Open a round trace on a state.  Helper that mirrors _open_round_trace
    without needing to hold the lock (we're single-threaded in tests)."""
    coord._open_round_trace(state, room_name, addressed)


@pytest.mark.asyncio
async def test_round_trace_records_first_response_timing(clean_trace_buffer):
    """on_agent_response stamps first_response_ms + reply_action on the trace."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-tr1",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
    )
    _attach_trace(state, "room-tr1", ["alice", "bob"])
    _cfn_state["room-tr1"] = state

    # Patch decide so the all-replied path doesn't try to call CFN.
    with patch.object(coord, "_cfn_decide_round", new=AsyncMock()):
        await on_agent_response("room-tr1", "alice", json.dumps({"action": "accept"}))

    slot = state.current_trace.per_agent["alice"]
    assert slot.first_response_ms is not None
    assert slot.first_response_ms >= 0.0
    assert slot.reply_action == "accept"
    assert slot.was_synthesised is False
    # Bob hasn't replied yet — trace slot is still pristine.
    assert state.current_trace.per_agent["bob"].first_response_ms is None
    assert state.current_trace.per_agent["bob"].reply_action is None

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_first_reply_wins_for_resubmits(clean_trace_buffer):
    """A second reply from the same handle does NOT overwrite first_response_ms.

    This matters because we want to measure how long the agent took to reach us
    the *first* time, not how long the resubmit took.
    """
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-tr2",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _attach_trace(state, "room-tr2", ["alice"])
    _cfn_state["room-tr2"] = state

    with patch.object(coord, "_cfn_decide_round", new=AsyncMock()):
        await on_agent_response("room-tr2", "alice", json.dumps({"action": "reject"}))
        first_ms = state.current_trace.per_agent["alice"].first_response_ms
        assert first_ms is not None
        # Resubmit with a different action — must not overwrite the stamp.
        await asyncio.sleep(0.01)
        await on_agent_response("room-tr2", "alice", json.dumps({"action": "accept"}))

    slot = state.current_trace.per_agent["alice"]
    assert slot.first_response_ms == first_ms
    # reply_action also stays as the first one — same rationale.
    assert slot.reply_action == "reject"

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_marks_synthesised_replies_on_watchdog_fire(clean_trace_buffer):
    """When _cfn_decide_round runs with missing replies, the trace records which
    handles got synthesised reject replies.  This is the data point that
    motivated #162 — observability into how often this happens in practice."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-tr3",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob", "carol"],
        # alice replied; bob and carol did not.
        pending_replies={
            "alice": {"agent_id": "alice", "participant_id": "alice", "action": "accept"},
            "bob": None,
            "carol": None,
        },
    )
    _attach_trace(state, "room-tr3", ["alice", "bob", "carol"])
    _cfn_state["room-tr3"] = state

    decide_response = {"status": "ongoing", "messages": []}

    with (
        patch(
            "app.services.cfn_negotiation.decide_negotiation",
            AsyncMock(return_value=decide_response),
        ),
        patch.object(coord, "_post_message", new=AsyncMock()),
        patch.object(coord, "async_session_maker"),
    ):
        await _cfn_decide_round("room-tr3", decision_path="watchdog_fired")

    # Round 0 is closed and emitted; round 1 has been opened.
    traces = coord.get_round_traces()
    assert len(traces) == 1
    closed = traces[0]
    assert closed["round_n"] == 0
    assert closed["decision_path"] == "watchdog_fired"
    assert closed["outcome"] == "ongoing"
    assert closed["synthesised_count"] == 2
    assert closed["synthesised_handles"] == ["bob", "carol"]
    assert closed["per_agent"]["alice"]["was_synthesised"] is False
    assert closed["per_agent"]["bob"]["was_synthesised"] is True

    # New round should be open with round_n incremented.
    assert state.round_n == 1
    assert state.current_trace is not None
    assert state.current_trace.round_n == 1

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_emitted_on_agreed_outcome(clean_trace_buffer):
    """Agreed terminal status closes and emits the trace before _finish_cfn."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-tr4",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": {"agent_id": "alice", "action": "accept"}},
    )
    _attach_trace(state, "room-tr4", ["alice"])
    _cfn_state["room-tr4"] = state

    decide_response = {
        "status": "agreed",
        "session_id": "room-tr4",
        "round": 1,
        "final_result": {
            "kind": "commit",
            "semantic_context": {
                "session_id": "room-tr4",
                "final_agreement": [{"issue_id": "x", "chosen_option": "y"}],
            },
            "payload": {"status": "agreed"},
        },
    }

    with (
        patch(
            "app.services.cfn_negotiation.decide_negotiation",
            AsyncMock(return_value=decide_response),
        ),
        patch.object(coord, "_post_message", new=AsyncMock()),
        patch.object(coord, "async_session_maker"),
    ):
        await _cfn_decide_round("room-tr4", decision_path="all_replied")

    traces = coord.get_round_traces()
    assert len(traces) == 1
    assert traces[0]["outcome"] == "agreed"
    assert traces[0]["decision_path"] == "all_replied"
    assert traces[0]["synthesised_count"] == 0

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_emitted_when_namespace_torn_down(clean_trace_buffer):
    """Aborting an in-flight round (room delete) flushes its trace as 'aborted'."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-tr5",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
    )
    _attach_trace(state, "room-tr5", ["alice", "bob"])
    _cfn_state["room-tr5"] = state

    asyncpg_patch, notify_patch = _patch_notify()
    with _patch_db(), asyncpg_patch, notify_patch:
        await coord.teardown_for_namespace("room-tr5", [])

    traces = coord.get_round_traces()
    assert len(traces) == 1
    assert traces[0]["outcome"] == "aborted"
    assert traces[0]["decision_path"] == "aborted"
    # Both agents had no real reply → both synthesised (recorded by the close,
    # not by the watchdog code path, but the marker is set the same way at
    # decide-time only — for an abort we just record the outcome).  Verify
    # the trace landed and includes both agents.
    assert set(traces[0]["per_agent"].keys()) == {"alice", "bob"}

    _cfn_state.clear()


def test_round_trace_buffer_is_bounded(clean_trace_buffer):
    """The trace ring buffer truncates to its capacity, oldest-out."""
    cap = coord.ROUND_TRACE_BUFFER_SIZE
    # Push cap + 5 traces directly via the emit helper.
    for i in range(cap + 5):
        trace = coord._RoundTrace(
            room_name=f"room-{i}",
            session_id=f"sess-{i}",
            mas_id="mas",
            workspace_id="ws",
            round_n=0,
            n_agents=1,
        )
        trace.decision_path = "all_replied"
        trace.outcome = "agreed"
        trace.closed_at = trace.started_at
        coord._emit_round_trace(trace)

    traces = coord.get_round_traces()
    assert len(traces) == cap
    # The oldest 5 should have been evicted (FIFO ring).
    assert traces[0]["room"] == "room-5"
    assert traces[-1]["room"] == f"room-{cap + 4}"


def test_get_round_traces_respects_limit(clean_trace_buffer):
    """get_round_traces(limit=N) returns the most-recent N entries."""
    for i in range(10):
        trace = coord._RoundTrace(
            room_name=f"room-{i}",
            session_id=f"sess-{i}",
            mas_id="mas",
            workspace_id="ws",
            round_n=0,
            n_agents=1,
        )
        trace.decision_path = "all_replied"
        trace.outcome = "agreed"
        trace.closed_at = trace.started_at
        coord._emit_round_trace(trace)

    last_three = coord.get_round_traces(limit=3)
    assert [t["room"] for t in last_three] == ["room-7", "room-8", "room-9"]
    assert coord.get_round_traces(limit=0) == []
    assert len(coord.get_round_traces()) == 10


def test_round_trace_to_json_shape(clean_trace_buffer):
    """The serialised trace has the documented schema fields and types."""
    trace = coord._RoundTrace(
        room_name="room-shape",
        session_id="sess-shape",
        mas_id="mas-shape",
        workspace_id="ws-shape",
        round_n=2,
        n_agents=2,
        per_agent={
            "alice": coord._PerAgentTrace(
                handle="alice", first_response_ms=123.456, reply_action="accept"
            ),
            "bob": coord._PerAgentTrace(handle="bob", was_synthesised=True),
        },
    )
    trace.decision_path = "watchdog_fired"
    trace.outcome = "ongoing"
    trace.closed_at = trace.started_at + 1.5  # 1500 ms

    record = trace.to_json()

    # Required top-level keys (the schema documented in app/routes/coordination.py).
    expected_keys = {
        "room",
        "session_id",
        "mas_id",
        "workspace_id",
        "round_n",
        "n_agents",
        "started_at",
        "elapsed_ms",
        "budget_seconds",
        "extension_count",
        "decision_path",
        "outcome",
        "synthesised_count",
        "synthesised_handles",
        "last_reply_received_ms",
        "cfn_decide_started_ms",
        "cfn_decide_ms",
        "cfn_status",
        "cfn_messages_count",
        "cfn_response_bytes",
        "cfn_internal_timing",
        "per_agent",
    }
    assert expected_keys.issubset(record.keys())
    # Decomposition fields default to None when never stamped.
    assert record["last_reply_received_ms"] is None
    assert record["cfn_decide_started_ms"] is None
    assert record["cfn_decide_ms"] is None
    assert record["cfn_status"] is None
    assert record["cfn_messages_count"] is None
    assert record["cfn_response_bytes"] is None
    assert record["cfn_internal_timing"] is None
    assert record["round_n"] == 2
    assert record["decision_path"] == "watchdog_fired"
    assert record["outcome"] == "ongoing"
    assert record["synthesised_count"] == 1
    assert record["synthesised_handles"] == ["bob"]
    assert record["elapsed_ms"] == 1500.0
    assert record["per_agent"]["alice"]["first_response_ms"] == 123.5
    assert record["per_agent"]["alice"]["reply_action"] == "accept"
    assert record["per_agent"]["alice"]["adapter"] == "unknown"
    assert record["per_agent"]["bob"]["was_synthesised"] is True
    # Must be JSON-serialisable end-to-end (no datetime objects, etc.).
    json.dumps(record)


@pytest.mark.asyncio
async def test_round_trace_decomposes_collection_vs_decide_latency(clean_trace_buffer):
    """End-to-end stamping of last_reply_received_ms / cfn_decide_started_ms /
    cfn_decide_ms.

    The collection phase ends when the last agent reply lands; the decide phase
    runs from there until /decide returns.  Splitting the two is the whole point
    of the decomposition — without it ``elapsed_ms`` rolls them together and
    callers can't tell agent latency apart from CFN latency.
    """
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-decomp",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _attach_trace(state, "room-decomp", ["alice"])
    _cfn_state["room-decomp"] = state

    # Make /decide take a measurable amount of time so cfn_decide_ms > 0.
    async def slow_decide(**_kwargs):
        await asyncio.sleep(0.05)
        return {
            "status": "agreed",
            "session_id": "room-decomp",
            "round": 1,
            "final_result": {
                "kind": "commit",
                "semantic_context": {
                    "session_id": "room-decomp",
                    "final_agreement": [{"issue_id": "x", "chosen_option": "y"}],
                },
                "payload": {"status": "agreed"},
            },
        }

    with (
        patch("app.services.cfn_negotiation.decide_negotiation", side_effect=slow_decide),
        patch.object(coord, "_post_message", new=AsyncMock()),
        patch.object(coord, "async_session_maker"),
    ):
        await on_agent_response("room-decomp", "alice", json.dumps({"action": "accept"}))
        # on_agent_response schedules _cfn_decide_round via ensure_future; let it run.
        for _ in range(20):
            await asyncio.sleep(0.01)
            if coord.get_round_traces():
                break

    traces = coord.get_round_traces()
    assert len(traces) == 1
    record = traces[0]

    # All three decomposition fields populated on the all_replied → agreed path.
    assert record["last_reply_received_ms"] is not None
    assert record["cfn_decide_started_ms"] is not None
    assert record["cfn_decide_ms"] is not None

    # Causal ordering: reply landed before decide started.
    assert record["cfn_decide_started_ms"] >= record["last_reply_received_ms"]

    # The 50 ms slow_decide sleep is comfortably observable; allow generous
    # slack for CI noise.
    assert record["cfn_decide_ms"] >= 40.0
    # And decide latency is bounded by total elapsed.
    assert record["cfn_decide_ms"] <= record["elapsed_ms"] + 1.0

    # CFN response shape stamped from the (mocked) decide payload.
    assert record["cfn_status"] == "agreed"
    # ``messages`` field is absent on the agreed payload above → count is None.
    assert record["cfn_messages_count"] is None
    assert isinstance(record["cfn_response_bytes"], int)
    assert record["cfn_response_bytes"] > 0

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_stamps_cfn_messages_count_on_ongoing(clean_trace_buffer):
    """Ongoing rounds should record how many mediator messages CFN returned —
    a multi-turn decide loop is the leading hypothesis for CFN-side latency in
    issue #162, and Mycelium can observe it directly from the response body."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-msgs",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice", "bob"],
        pending_replies={"alice": None, "bob": None},
    )
    _attach_trace(state, "room-msgs", ["alice", "bob"])
    _cfn_state["room-msgs"] = state

    async def ongoing_with_three_messages(**_kwargs):
        return {
            "status": "ongoing",
            "messages": [
                {"to": "alice", "content": "..."},
                {"to": "bob", "content": "..."},
                {"to": "alice", "content": "..."},
            ],
        }

    with (
        patch(
            "app.services.cfn_negotiation.decide_negotiation",
            side_effect=ongoing_with_three_messages,
        ),
        patch.object(coord, "_post_message", new=AsyncMock()),
        patch.object(coord, "_fan_out_cfn_messages", new=AsyncMock(return_value=["alice", "bob"])),
        patch.object(coord, "async_session_maker"),
    ):
        await on_agent_response("room-msgs", "alice", json.dumps({"action": "accept"}))
        await on_agent_response("room-msgs", "bob", json.dumps({"action": "accept"}))
        for _ in range(20):
            await asyncio.sleep(0.01)
            if coord.get_round_traces():
                break

    traces = coord.get_round_traces()
    assert len(traces) == 1
    assert traces[0]["cfn_status"] == "ongoing"
    assert traces[0]["cfn_messages_count"] == 3
    assert isinstance(traces[0]["cfn_response_bytes"], int)
    assert traces[0]["cfn_response_bytes"] > 0

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_captures_cfn_internal_timing_envelope(clean_trace_buffer):
    """When CFN returns a ``_timing`` envelope (the experimental patched build),
    capture it verbatim so the analyzer can decompose where /decide spent its
    wall-clock time without log scraping.

    Tolerance is critical: this code must also run against unpatched CFN
    images that don't emit ``_timing`` at all (covered by the agreed/ongoing
    tests above where the field is absent and stays ``None``)."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-timing",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": None},
    )
    _attach_trace(state, "room-timing", ["alice"])
    _cfn_state["room-timing"] = state

    async def decide_with_timing(**_kwargs):
        return {
            "status": "agreed",
            "session_id": "room-timing",
            "round": 1,
            "final_result": {
                "kind": "commit",
                "semantic_context": {
                    "session_id": "room-timing",
                    "final_agreement": [{"issue_id": "x", "chosen_option": "y"}],
                },
                "payload": {"status": "agreed"},
            },
            # The experimental envelope CFN attaches when patched.  Mix int and
            # float to confirm both pass the type filter.
            "_timing": {
                "validate_ms": 1,
                "pipeline_ms": 22500.7,
                "to_dict_ms": 12.3,
                "thread_wait_ms": 0.4,
                "in_thread_ms": 22480.0,
                "total_route_ms": 22515.0,
                # Junk that should be silently filtered out.
                "nested_dict_should_be_dropped": {"foo": "bar"},
                42: "non-string-key-should-be-dropped",
            },
        }

    with (
        patch("app.services.cfn_negotiation.decide_negotiation", side_effect=decide_with_timing),
        patch.object(coord, "_post_message", new=AsyncMock()),
        patch.object(coord, "async_session_maker"),
    ):
        await on_agent_response("room-timing", "alice", json.dumps({"action": "accept"}))
        for _ in range(20):
            await asyncio.sleep(0.01)
            if coord.get_round_traces():
                break

    traces = coord.get_round_traces()
    assert len(traces) == 1
    timing = traces[0]["cfn_internal_timing"]
    assert isinstance(timing, dict)
    # All numeric stages preserved.
    assert timing["pipeline_ms"] == 22500.7
    assert timing["thread_wait_ms"] == 0.4
    assert timing["in_thread_ms"] == 22480.0
    # Junk filtered out by the captor.
    assert "nested_dict_should_be_dropped" not in timing
    assert 42 not in timing

    _cfn_state.clear()


@pytest.mark.asyncio
async def test_round_trace_decide_latency_stamped_when_cfn_call_raises(clean_trace_buffer):
    """Even when ``decide_negotiation`` raises, the trace records how long the
    failed call took — otherwise CFN errors would look instantaneous."""
    _cfn_state.clear()
    state = _CfnRoundState(
        session_id="room-decomp-err",
        workspace_id="ws",
        mas_id="mas",
        agents=["alice"],
        pending_replies={"alice": {"agent_id": "alice", "action": "accept"}},
    )
    _attach_trace(state, "room-decomp-err", ["alice"])
    _cfn_state["room-decomp-err"] = state

    from app.services.cfn_negotiation import CfnNegotiationError

    async def failing_decide(**_kwargs):
        await asyncio.sleep(0.02)
        raise CfnNegotiationError("simulated CFN failure")

    with (
        patch("app.services.cfn_negotiation.decide_negotiation", side_effect=failing_decide),
        patch.object(coord, "_post_message", new=AsyncMock()),
        patch.object(coord, "async_session_maker"),
    ):
        await coord._cfn_decide_round("room-decomp-err", decision_path="all_replied")

    traces = coord.get_round_traces()
    assert len(traces) == 1
    assert traces[0]["outcome"] == "error"
    assert traces[0]["cfn_decide_started_ms"] is not None
    assert traces[0]["cfn_decide_ms"] is not None
    assert traces[0]["cfn_decide_ms"] >= 15.0  # ≥ the 20 ms sleep (slack for CI)

    _cfn_state.clear()
