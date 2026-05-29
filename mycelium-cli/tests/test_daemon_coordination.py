# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon-side ``coordination_tick`` / ``coordination_consensus`` handling.

Pins the autonomous-negotiation invariant for cold-spawn families: when the
CognitiveEngine emits a tick or consensus message, the cc-daemon spawns the
addressed agent with a self-contained instruction so it can run
``mycelium negotiate respond accept`` (or the propose/reject equivalents)
itself — no operator-driven accept loop required.

Mirrors the openclaw ``routeTick`` / ``routeConsensus`` invariants so
cold-spawn agents (cursor + claude_code) see the same prompt the openclaw
agent runtime sees today. Without these tests a regression in the daemon
would silently fall back to the operator-driven path, which is exactly the
gap the cursor-e2e Phase 5 walkthrough surfaced before this branch landed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.daemon import config as daemon_config
from mycelium.daemon import dispatch
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState
from mycelium.protocol import AgentManifest


@pytest.fixture(autouse=True)
def _tmp_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_config, "daemon_config_path", lambda: tmp_path / "cc-daemon.toml")


def _config() -> MyceliumConfig:
    return MyceliumConfig(server=ServerConfig(api_url="http://localhost:8000"))


def _manifest(handle: str, cwd: str = "/tmp/x") -> AgentManifest:
    return AgentManifest(
        handle=handle,
        adapter="cursor",
        cwd=cwd,
        description="negotiation participant",
    )


# ── _format_tick_instruction — round, action, CLI commands ────────────────────


def test_format_tick_includes_round_and_action() -> None:
    instr = dispatch._format_tick_instruction(
        {"payload": {"round": 5, "action": "propose", "can_counter_offer": True}},
        "my-room",
        "designer",
    )
    assert "Round 5" in instr
    assert "Action required: propose" in instr


def test_format_tick_includes_room_and_handle_in_cli_commands() -> None:
    instr = dispatch._format_tick_instruction(
        {"payload": {"round": 1, "action": "respond"}},
        "api-debate",
        "designer",
    )
    # Core invariant: the agent must be able to copy/paste these.
    assert "--room api-debate" in instr
    assert "--handle designer" in instr
    assert "mycelium negotiate respond accept" in instr
    assert "mycelium negotiate respond reject" in instr


def test_format_tick_shows_propose_command_when_can_counter() -> None:
    instr = dispatch._format_tick_instruction(
        {"payload": {"round": 1, "action": "propose", "can_counter_offer": True}},
        "r",
        "a",
    )
    assert "mycelium negotiate propose" in instr


def test_format_tick_omits_propose_command_when_cannot_counter() -> None:
    instr = dispatch._format_tick_instruction(
        {"payload": {"round": 1, "action": "respond", "can_counter_offer": False}},
        "r",
        "a",
    )
    assert "mycelium negotiate propose" not in instr


def test_format_tick_lists_current_offer_fields() -> None:
    instr = dispatch._format_tick_instruction(
        {"payload": {"round": 1, "current_offer": {"price": "500k", "timeline": "30 days"}}},
        "r",
        "a",
    )
    assert "price: 500k" in instr
    assert "timeline: 30 days" in instr


def test_format_tick_lists_valid_offer_keys_when_counter_allowed() -> None:
    instr = dispatch._format_tick_instruction(
        {
            "payload": {
                "round": 1,
                "action": "propose",
                "can_counter_offer": True,
                "current_offer": {"Cache TTL": "600", "Eviction Policy": "LRU"},
            }
        },
        "r",
        "a",
    )
    # Key-name fidelity matters — agents have miscoded keys without this hint
    # (#276 / #285 from the openclaw side; pinned here too).
    assert "Valid offer keys" in instr
    assert '"Cache TTL"' in instr
    assert '"Eviction Policy"' in instr


def test_format_tick_omits_valid_keys_line_when_cannot_counter() -> None:
    instr = dispatch._format_tick_instruction(
        {
            "payload": {
                "round": 1,
                "action": "respond",
                "can_counter_offer": False,
                "current_offer": {"Cache TTL": "600"},
            }
        },
        "r",
        "a",
    )
    assert "Valid offer keys" not in instr


def test_format_tick_renders_shared_context_files() -> None:
    instr = dispatch._format_tick_instruction(
        {
            "payload": {
                "round": 1,
                "action": "respond",
                "current_offer": {},
                "shared_context_files": [
                    {
                        "shared_by": "alpha",
                        "path": "/agents/alpha/SOUL.md",
                        "content": "I value privacy and clarity.",
                    }
                ],
            }
        },
        "r",
        "alpha",
    )
    assert "Shared context files" in instr
    assert "/agents/alpha/SOUL.md" in instr
    assert "shared by alpha" in instr
    assert "I value privacy and clarity." in instr


def test_format_tick_renders_plan_open_tasks_when_present() -> None:
    instr = dispatch._format_tick_instruction(
        {
            "payload": {
                "round": 1,
                "action": "respond",
                "current_offer": {},
                "plan_open_tasks": "Open tasks (2):\n- [tasks] write the parser",
            }
        },
        "r",
        "a",
    )
    assert "Open tasks (2)" in instr
    assert "write the parser" in instr


def test_format_tick_includes_walk_away_guidance() -> None:
    """The agent must be told that walking away is a legitimate outcome.

    Without this guidance an LLM tends to accept just to satisfy the prompt,
    which silently degrades negotiation quality. The openclaw plugin pins
    the same line; we mirror it here.
    """
    instr = dispatch._format_tick_instruction(
        {"payload": {"round": 1, "action": "respond"}},
        "r",
        "a",
    )
    assert "Walking away" in instr


# ── _format_error_tick — error kind, instruction, recovery commands ──────────


def test_format_error_tick_invalid_keys_renders_recovery_command() -> None:
    instr = dispatch._format_tick_instruction(
        {
            "error": "counter_offer_invalid_keys",
            "instruction": "Re-submit your counter_offer using only the valid keys.",
            "valid_keys": ["Cache TTL", "Eviction Policy"],
            "bad_keys": ["cache_ttl", "eviction_policy"],
            "payload": {"participant_id": "designer"},
        },
        "my-room",
        "designer",
    )
    assert "counter_offer_invalid_keys" in instr
    assert "Re-submit your counter_offer" in instr
    assert '"Cache TTL"' in instr
    assert '"Eviction Policy"' in instr
    assert '"cache_ttl"' in instr
    assert "Recovery: mycelium negotiate propose" in instr
    assert "--room my-room" in instr
    assert "--handle designer" in instr


def test_format_error_tick_not_your_turn_renders_accept_reject_recovery() -> None:
    instr = dispatch._format_tick_instruction(
        {
            "error": "counter_offer_not_your_turn",
            "instruction": "It is not your turn to propose.",
            "payload": {"participant_id": "designer"},
        },
        "r",
        "designer",
    )
    assert "counter_offer_not_your_turn" in instr
    assert "It is not your turn to propose." in instr
    assert "mycelium negotiate respond accept" in instr
    assert "mycelium negotiate respond reject" in instr


# ── _format_consensus_summary ────────────────────────────────────────────────


def test_format_consensus_lists_assignments() -> None:
    summary = dispatch._format_consensus_summary(
        {
            "plan": "ship date=Q4; design polish=2 cycles",
            "assignments": {"ship date": "Q4", "design polish": "2 cycles"},
        }
    )
    assert "Consensus Reached" in summary
    assert "ship date: Q4" in summary
    assert "design polish: 2 cycles" in summary


def test_format_consensus_renders_plan_file_pointer() -> None:
    summary = dispatch._format_consensus_summary(
        {"plan": "p", "assignments": {}, "plan_file": "plan/tasks.md"}
    )
    assert "plan/tasks.md" in summary
    assert "mycelium plan tasks" in summary


def test_format_consensus_broken_returns_failure_message() -> None:
    summary = dispatch._format_consensus_summary(
        {"plan": "irreconcilable positions on price", "broken": True}
    )
    assert "Negotiation FAILED" in summary
    assert "irreconcilable positions" in summary
    # No assignments section on a broken negotiation — agents shouldn't act
    # on a non-existent plan.
    assert "Assignments:" not in summary


# ── on_message routing — coordination_tick ───────────────────────────────────


def _make_state() -> DaemonState:
    return DaemonState()


def _async(coro):  # type: ignore[no-untyped-def]
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def _patched_dispatch(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Patch the side-effectful pieces ``_handle_tick`` calls into.

    ``_dispatch_one`` is the integration boundary — tests assert it gets
    called with the expected manifest + prompt rather than running a real
    cold spawn. ``load_manifest`` is patched per-test to control what shows
    up under ``agents/<handle>``.
    """
    dispatch_one = MagicMock()

    async def _fake_dispatch_one(**kwargs: Any) -> None:
        dispatch_one(**kwargs)

    monkeypatch.setattr(dispatch, "_dispatch_one", _fake_dispatch_one)
    return {"dispatch_one": dispatch_one}


@pytest.mark.asyncio
async def test_on_message_dispatches_tick_to_owned_handle(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest("designer")
    monkeypatch.setattr(
        dispatch, "load_manifest", lambda room, handle: manifest if handle == "designer" else None
    )

    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "tick-1",
        "message_type": "coordination_tick",
        "room_name": "r:session:abc",
        "content": json.dumps(
            {
                "payload": {
                    "participant_id": "designer",
                    "round": 1,
                    "action": "respond",
                    "can_counter_offer": False,
                    "current_offer": {"price": "500"},
                }
            }
        ),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r:session:abc",
        msg=msg,
    )
    # _dispatch_one is fired as a Task; let the loop run.
    await asyncio.sleep(0)

    dispatch_one = _patched_dispatch["dispatch_one"]
    dispatch_one.assert_called_once()
    kwargs = dispatch_one.call_args.kwargs
    assert kwargs["manifest"].handle == "designer"
    assert kwargs["sender_handle"] == "CognitiveEngine"
    # The prompt must be a self-contained instruction, not the raw JSON.
    assert "mycelium negotiate respond accept" in kwargs["prompt"]
    assert "--handle designer" in kwargs["prompt"]
    assert "--room r:session:abc" in kwargs["prompt"]


@pytest.mark.asyncio
async def test_on_message_skips_tick_for_unowned_handle(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling daemon's tick must not trigger a cold spawn here."""
    monkeypatch.setattr(dispatch, "load_manifest", lambda room, handle: _manifest(handle))

    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])  # NOT planner
    state = _make_state()
    msg = {
        "id": "tick-2",
        "message_type": "coordination_tick",
        "room_name": "r",
        "content": json.dumps({"payload": {"participant_id": "planner", "round": 1}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=msg,
    )
    await asyncio.sleep(0)

    _patched_dispatch["dispatch_one"].assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_tick_with_unparseable_content(
    _patched_dispatch: dict[str, MagicMock],
) -> None:
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "tick-3",
        "message_type": "coordination_tick",
        "content": "{this is not json",
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=msg,
    )
    await asyncio.sleep(0)
    _patched_dispatch["dispatch_one"].assert_not_called()


@pytest.mark.asyncio
async def test_on_message_skips_tick_for_long_lived_gateway_family(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Openclaw agents have their own runtime tick handler; cc-daemon must
    not also spawn — that would race with the gateway."""
    openclaw_manifest = AgentManifest(
        handle="planner",
        adapter="openclaw",
        openclaw_agent="planner",
        description="ll gateway",
    )
    monkeypatch.setattr(dispatch, "load_manifest", lambda room, handle: openclaw_manifest)

    daemon_cfg = DaemonConfig(rooms=["r"], handles=["planner"])
    state = _make_state()
    msg = {
        "id": "tick-4",
        "message_type": "coordination_tick",
        "content": json.dumps({"payload": {"participant_id": "planner", "round": 1}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=msg,
    )
    await asyncio.sleep(0)

    _patched_dispatch["dispatch_one"].assert_not_called()


# ── on_message routing — coordination_consensus ──────────────────────────────


@pytest.mark.asyncio
async def test_on_message_dispatches_consensus_to_each_owned_handle(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatch, "list_agent_handles", lambda room: ["designer", "planner", "x"])

    def _load(room: str, handle: str) -> AgentManifest | None:
        if handle in {"designer", "planner"}:
            return _manifest(handle)
        return None

    monkeypatch.setattr(dispatch, "load_manifest", _load)

    # designer + planner are owned here; x is in the room but on a sibling.
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer", "planner"])
    state = _make_state()
    msg = {
        "id": "cons-1",
        "message_type": "coordination_consensus",
        "room_name": "r:session:abc",
        "content": json.dumps(
            {
                "plan": "ship date=Q4; design polish=2 cycles",
                "assignments": {"ship date": "Q4", "design polish": "2 cycles"},
                "broken": False,
                "plan_file": "plan/tasks.md",
            }
        ),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r:session:abc",
        msg=msg,
    )
    # Two scheduled tasks (designer + planner); flush.
    await asyncio.sleep(0)

    dispatch_one = _patched_dispatch["dispatch_one"]
    assert dispatch_one.call_count == 2
    handles_dispatched = {call.kwargs["manifest"].handle for call in dispatch_one.call_args_list}
    assert handles_dispatched == {"designer", "planner"}
    summary_prompt = dispatch_one.call_args_list[0].kwargs["prompt"]
    assert "Consensus Reached" in summary_prompt
    assert "plan/tasks.md" in summary_prompt


@pytest.mark.asyncio
async def test_on_message_consensus_skips_unowned_handles(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatch, "list_agent_handles", lambda room: ["x"])
    monkeypatch.setattr(dispatch, "load_manifest", lambda room, handle: _manifest(handle))

    daemon_cfg = DaemonConfig(rooms=["r"], handles=[])  # owns nothing
    state = _make_state()
    msg = {
        "id": "cons-2",
        "message_type": "coordination_consensus",
        "content": json.dumps({"plan": "p", "assignments": {}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=msg,
    )
    await asyncio.sleep(0)

    _patched_dispatch["dispatch_one"].assert_not_called()


# ── on_message routing — coordination_join → dynamic session subscribe ───────


@pytest.fixture
def _patched_subscribe(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``subscribe_room`` so ``_handle_join`` doesn't open a real SSE
    connection. Tests assert the dynamic task gets created with the right
    sub-room name; the SSE pump itself is exercised separately."""
    subscribe = MagicMock()

    async def _fake_subscribe(**kwargs: Any) -> None:
        subscribe(**kwargs)

    monkeypatch.setattr(dispatch, "subscribe_room", _fake_subscribe)
    return subscribe


@pytest.mark.asyncio
async def test_on_message_join_subscribes_session_subroom_from_content(
    _patched_subscribe: MagicMock,
) -> None:
    """A coordination_join broadcast in the parent room carries the session
    sub-room name in its JSON content; the daemon must extract it and fire
    a dynamic subscribe so subsequent ticks (which only land in the
    sub-room) are observed."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "join-1",
        "message_type": "coordination_join",
        "room_name": "r",  # parent room — sub-room is in content.session
        "sender_handle": "CognitiveEngine",
        "content": json.dumps(
            {"handle": "designer", "intent": "polish", "session": "r:session:abc"}
        ),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=msg,
    )
    await asyncio.sleep(0)

    _patched_subscribe.assert_called_once()
    assert _patched_subscribe.call_args.kwargs["room_name"] == "r:session:abc"
    assert "r:session:abc" in state.session_room_tasks


@pytest.mark.asyncio
async def test_on_message_join_subscribes_when_room_name_is_session_subroom(
    _patched_subscribe: MagicMock,
) -> None:
    """Some joins are observed already inside the sub-room (e.g. when the
    daemon is also subscribed to mirror events). Use ``msg.room_name``
    directly in that case."""
    daemon_cfg = DaemonConfig(rooms=["r:session:abc"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "join-2",
        "message_type": "coordination_join",
        "room_name": "r:session:abc",
        "content": json.dumps({"handle": "designer"}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r:session:abc",
        msg=msg,
    )
    await asyncio.sleep(0)

    _patched_subscribe.assert_called_once()
    assert _patched_subscribe.call_args.kwargs["room_name"] == "r:session:abc"


@pytest.mark.asyncio
async def test_on_message_join_subscription_is_idempotent(
    _patched_subscribe: MagicMock,
) -> None:
    """Repeated joins (or coordination_start after the join) must not spawn
    competing SSE listeners on the same sub-room."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    join_msg = {
        "id": "join-3a",
        "message_type": "coordination_join",
        "room_name": "r",
        "content": json.dumps({"handle": "designer", "session": "r:session:abc"}),
    }
    start_msg = {
        "id": "join-3b",
        "message_type": "coordination_start",
        "room_name": "r:session:abc",
        "content": json.dumps({"round": 0}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=join_msg,
    )
    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r:session:abc",
        msg=start_msg,
    )
    await asyncio.sleep(0)

    _patched_subscribe.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_join_without_session_pointer_is_a_no_op(
    _patched_subscribe: MagicMock,
) -> None:
    """A join that doesn't carry a session sub-room (malformed) shouldn't
    crash or fire spurious subscriptions."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "join-4",
        "message_type": "coordination_join",
        "room_name": "r",
        "content": "{not json",
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r",
        msg=msg,
    )
    await asyncio.sleep(0)
    _patched_subscribe.assert_not_called()


# ── parent-room derivation in tick / consensus ───────────────────────────────


@pytest.mark.asyncio
async def test_handle_tick_looks_up_manifest_under_parent_room_not_subroom(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ticks always arrive in a session sub-room (``parent:session:<id>``)
    because that's the only channel CognitiveEngine NOTIFY's on. Manifests
    are mirrored under the *parent* room, so the lookup must derive the
    parent — otherwise every tick stalls with "no manifest in local mirror"
    even though the agent is registered correctly. This was the live failure
    mode that surfaced when the cc-daemon first started subscribing to
    session sub-rooms in 2026-05.
    """
    seen_rooms: list[str] = []

    def _load(room: str, handle: str) -> AgentManifest | None:
        seen_rooms.append(room)
        return _manifest(handle)

    monkeypatch.setattr(dispatch, "load_manifest", _load)

    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "tick-parent-1",
        "message_type": "coordination_tick",
        "room_name": "cursor-ioc-e2e:session:abc123",
        "content": json.dumps({"payload": {"participant_id": "designer", "round": 1}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="cursor-ioc-e2e:session:abc123",
        msg=msg,
    )
    await asyncio.sleep(0)

    # Must have looked up the parent — never the sub-room — for the manifest.
    assert seen_rooms == ["cursor-ioc-e2e"]


@pytest.mark.asyncio
async def test_handle_tick_manifest_lookup_uses_room_name_when_not_a_subroom(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent-room derivation is `split(":session:")[0]`, so a room name
    that doesn't contain ``:session:`` must round-trip unchanged. Pinning
    this guards against an over-eager refactor that always strips a colon
    suffix and breaks rooms named like ``foo:bar``."""
    seen_rooms: list[str] = []

    def _load(room: str, handle: str) -> AgentManifest | None:
        seen_rooms.append(room)
        return _manifest(handle)

    monkeypatch.setattr(dispatch, "load_manifest", _load)

    daemon_cfg = DaemonConfig(rooms=["foo:bar"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "tick-parent-2",
        "message_type": "coordination_tick",
        "room_name": "foo:bar",
        "content": json.dumps({"payload": {"participant_id": "designer", "round": 1}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="foo:bar",
        msg=msg,
    )
    await asyncio.sleep(0)

    assert seen_rooms == ["foo:bar"]


@pytest.mark.asyncio
async def test_handle_tick_dispatch_uses_subroom_for_response_room(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the manifest lookup uses the parent, the dispatched prompt and
    ``room_name`` must point at the sub-room — otherwise the agent's
    ``mycelium negotiate respond`` lands in the parent room and the engine
    never sees it."""
    monkeypatch.setattr(dispatch, "load_manifest", lambda room, handle: _manifest(handle))

    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "tick-parent-3",
        "message_type": "coordination_tick",
        "room_name": "r:session:xyz",
        "content": json.dumps({"payload": {"participant_id": "designer", "round": 1}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="r:session:xyz",
        msg=msg,
    )
    await asyncio.sleep(0)

    kwargs = _patched_dispatch["dispatch_one"].call_args.kwargs
    assert kwargs["room_name"] == "r:session:xyz"
    assert "--room r:session:xyz" in kwargs["prompt"]


@pytest.mark.asyncio
async def test_handle_consensus_lists_handles_under_parent_room(
    _patched_dispatch: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``coordination_consensus`` mirrors the same parent-vs-subroom split:
    list_agent_handles + load_manifest both target the parent room (where
    the manifests live), even though the consensus message itself arrives
    in the sub-room."""
    seen_listed: list[str] = []
    seen_manifest_lookups: list[str] = []

    def _list(room: str) -> list[str]:
        seen_listed.append(room)
        return ["designer"]

    def _load(room: str, handle: str) -> AgentManifest | None:
        seen_manifest_lookups.append(room)
        return _manifest(handle)

    monkeypatch.setattr(dispatch, "list_agent_handles", _list)
    monkeypatch.setattr(dispatch, "load_manifest", _load)

    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    msg = {
        "id": "cons-parent-1",
        "message_type": "coordination_consensus",
        "room_name": "cursor-ioc-e2e:session:abc",
        "content": json.dumps({"plan": "p", "assignments": {"k": "v"}}),
    }

    await dispatch.on_message(
        config=_config(),
        daemon_cfg=daemon_cfg,
        state=state,
        room_name="cursor-ioc-e2e:session:abc",
        msg=msg,
    )
    await asyncio.sleep(0)

    assert seen_listed == ["cursor-ioc-e2e"]
    assert seen_manifest_lookups == ["cursor-ioc-e2e"]
    # Reply room is still the sub-room so the consensus broadcast lands in
    # the right session, not the noisy parent.
    kwargs = _patched_dispatch["dispatch_one"].call_args.kwargs
    assert kwargs["room_name"] == "cursor-ioc-e2e:session:abc"


# ── poll_coordination_sessions — dynamic session sub-room subscription ───────


class _FakeResponse:
    """Stand-in for ``httpx.Response`` returned by the fake AsyncClient."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise RuntimeError(f"status {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    """Stand-in for ``httpx.AsyncClient`` — yields canned payloads in order.

    Mirrors only the surface the poller touches: ``async with`` context plus
    ``await client.get(url, params=…)``. An optional ``on_request`` hook lets
    a test set ``state.stopping`` after the first poll so the loop exits
    deterministically without leaning on real-time waits.
    """

    def __init__(
        self,
        payloads: list[Any],
        *,
        on_request: Any = None,
        timeout: Any = None,
    ) -> None:
        self._payloads = list(payloads)
        self._on_request = on_request

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        if self._on_request is not None:
            self._on_request()
        if not self._payloads:
            return _FakeResponse([])
        return _FakeResponse(self._payloads.pop(0))


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    payloads: list[Any],
    *,
    on_request: Any = None,
) -> None:
    """Patch ``dispatch.httpx.AsyncClient`` to return our fake.

    Captures the constructor kwargs by closing over them — tests assert on
    what the poller called us with.
    """

    def _factory(*args: Any, **kwargs: Any) -> _FakeAsyncClient:
        return _FakeAsyncClient(payloads, on_request=on_request)

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", _factory)


@pytest.fixture
def _patched_subscribe_async(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stand-in for ``subscribe_room`` used by the poller tests.

    The real ``subscribe_room`` is a long-lived coroutine that parks on the
    SSE pump — it never returns on its own. The fake mirrors that shape so
    the poller's ``existing.done()`` check sees in-flight subscriptions as
    still alive across polls (which is the production invariant). Each
    test is responsible for cancelling ``state.session_room_tasks`` in a
    ``finally`` block so the parked coroutines don't leak across tests.
    """
    calls = MagicMock()

    async def _fake_subscribe(**kwargs: Any) -> None:
        calls(**kwargs)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return

    monkeypatch.setattr(dispatch, "subscribe_room", _fake_subscribe)
    return calls


async def _drain_session_tasks(state: DaemonState) -> None:
    """Cancel and await every task in ``state.session_room_tasks``.

    Pytest will warn (and fail under strict mode) if a test leaves
    pending Tasks behind. The poller tests intentionally start tasks
    that park forever (matching real SSE pump behaviour), so each test
    has to call this in a ``finally`` to clean up.
    """
    tasks = list(state.session_room_tasks.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    state.session_room_tasks.clear()


@pytest.mark.asyncio
async def test_poller_subscribes_to_active_session(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core invariant: a session in ``negotiating`` state on the
    backend produces exactly one dynamic SSE subscription on the
    daemon."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()

    poll_count = {"n": 0}

    def _on_request() -> None:
        # Stop after the *second* poll so the subscribe task created in
        # poll 1 has a chance to run (and block on its parked Event)
        # during the 0.01 s ``wait_for`` between polls. If we set
        # stopping during poll 1, ``wait_for`` returns synchronously and
        # the create_task'd subscribe coroutine never gets scheduled.
        poll_count["n"] += 1
        if poll_count["n"] >= 2:
            state.stopping.set()

    same_session = [{"display_name": "r:session:abc", "state": "negotiating"}]
    _install_fake_httpx(
        monkeypatch,
        [same_session, same_session],
        on_request=_on_request,
    )
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 0.01)

    try:
        await dispatch.poll_coordination_sessions(
            config=_config(), daemon_cfg=daemon_cfg, state=state
        )
    finally:
        await _drain_session_tasks(state)

    # Subscribed exactly once even though the session showed up on both
    # polls — the second poll sees the parked task and skips.
    _patched_subscribe_async.assert_called_once()
    assert _patched_subscribe_async.call_args.kwargs["room_name"] == "r:session:abc"


@pytest.mark.asyncio
async def test_poller_skips_terminal_sessions(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessions that have already concluded (``complete``, ``failed``,
    ``agreed``, ``idle``) must not pin SSE connections — otherwise a long-
    running daemon accumulates dead listeners."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()

    _install_fake_httpx(
        monkeypatch,
        [
            [
                {"display_name": "r:session:done", "state": "complete"},
                {"display_name": "r:session:bad", "state": "failed"},
                {"display_name": "r:session:idle", "state": "idle"},
            ]
        ],
        on_request=lambda: state.stopping.set(),
    )
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 0.01)

    try:
        await dispatch.poll_coordination_sessions(
            config=_config(), daemon_cfg=daemon_cfg, state=state
        )
    finally:
        await _drain_session_tasks(state)

    _patched_subscribe_async.assert_not_called()
    assert state.session_room_tasks == {}


@pytest.mark.asyncio
async def test_poller_ignores_entries_without_session_marker(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: a malformed/legacy row without ``:session:`` in
    the display name must not be treated as a sub-room — those would
    yield bogus SSE URLs."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()

    _install_fake_httpx(
        monkeypatch,
        [
            [
                {"display_name": "plain-room-no-marker", "state": "negotiating"},
                {"display_name": None, "state": "negotiating"},
                {"state": "negotiating"},  # missing display_name entirely
            ]
        ],
        on_request=lambda: state.stopping.set(),
    )
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 0.01)

    try:
        await dispatch.poll_coordination_sessions(
            config=_config(), daemon_cfg=daemon_cfg, state=state
        )
    finally:
        await _drain_session_tasks(state)

    _patched_subscribe_async.assert_not_called()


@pytest.mark.asyncio
async def test_poller_subscription_is_idempotent_across_polls(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a still-active session shows up on three consecutive polls,
    the poller must not re-subscribe (the in-flight task is still
    healthy). Without this we'd open N SSE connections for one session
    over time."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    poll_count = {"n": 0}

    def _on_request() -> None:
        poll_count["n"] += 1
        if poll_count["n"] >= 3:
            state.stopping.set()

    same_session = [{"display_name": "r:session:abc", "state": "negotiating"}]
    _install_fake_httpx(
        monkeypatch,
        [same_session, same_session, same_session],
        on_request=_on_request,
    )
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 0.01)

    try:
        await dispatch.poll_coordination_sessions(
            config=_config(), daemon_cfg=daemon_cfg, state=state
        )
    finally:
        await _drain_session_tasks(state)

    _patched_subscribe_async.assert_called_once()


@pytest.mark.asyncio
async def test_poller_unsubscribes_when_session_leaves_active_set(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session present on poll N but absent on poll N+1 (or moved to a
    terminal state) must have its SSE task cancelled and dropped from
    ``session_room_tasks``. Without this, the daemon would pin a closed
    connection per completed negotiation forever."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    poll_count = {"n": 0}

    def _on_request() -> None:
        poll_count["n"] += 1
        if poll_count["n"] >= 2:
            state.stopping.set()

    _install_fake_httpx(
        monkeypatch,
        [
            [{"display_name": "r:session:abc", "state": "negotiating"}],
            [],  # next poll: session gone
        ],
        on_request=_on_request,
    )
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 0.01)

    try:
        await dispatch.poll_coordination_sessions(
            config=_config(), daemon_cfg=daemon_cfg, state=state
        )
    finally:
        await _drain_session_tasks(state)

    assert "r:session:abc" not in state.session_room_tasks


@pytest.mark.asyncio
async def test_poller_survives_backend_failure(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient backend hiccup (timeout, 5xx, connection refused) must
    not crash the daemon's coordination discovery — the next poll tick
    should retry as normal."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    poll_count = {"n": 0}

    class _FlakyClient:
        async def __aenter__(self) -> _FlakyClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

        async def get(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            poll_count["n"] += 1
            if poll_count["n"] == 1:
                raise RuntimeError("simulated backend outage")
            return _FakeResponse([{"display_name": "r:session:abc", "state": "negotiating"}])

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", lambda *a, **kw: _FlakyClient())
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 0.01)

    # Stop after the third poll so the subscribe scheduled on poll 2 has a
    # chance to run during poll 2 → poll 3 wait_for window.
    async def _watch_and_stop() -> None:
        while poll_count["n"] < 3:
            await asyncio.sleep(0.01)
        state.stopping.set()

    watcher = asyncio.create_task(_watch_and_stop())
    try:
        await dispatch.poll_coordination_sessions(
            config=_config(), daemon_cfg=daemon_cfg, state=state
        )
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
        await _drain_session_tasks(state)

    # First poll raised; second poll subscribed → loop survived.
    _patched_subscribe_async.assert_called_once()
    assert _patched_subscribe_async.call_args.kwargs["room_name"] == "r:session:abc"


@pytest.mark.asyncio
async def test_poller_exits_promptly_when_stopping_is_set(
    _patched_subscribe_async: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daemon shutdown sets ``state.stopping``. The poller must observe
    that and return rather than blocking the runner's task-cancellation
    sequence on a stale 5-second sleep."""
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["designer"])
    state = _make_state()
    state.stopping.set()  # already stopping before the poller starts

    _install_fake_httpx(monkeypatch, [])
    monkeypatch.setattr(dispatch, "_SESSION_POLL_INTERVAL_S", 30.0)

    # If the poller honoured stopping it returns immediately. If it didn't,
    # ``wait_for`` would block for 30 s and pytest would hit its own
    # timeout — that's the failure mode this test pins.
    try:
        await asyncio.wait_for(
            dispatch.poll_coordination_sessions(
                config=_config(), daemon_cfg=daemon_cfg, state=state
            ),
            timeout=2.0,
        )
    finally:
        await _drain_session_tasks(state)
