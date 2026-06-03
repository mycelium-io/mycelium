# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the hermes plugin's route formatter.

The plugin tree under ``integrations/hermes/assets/mycelium/plugin/`` is
staged into ``~/.hermes/plugins/mycelium/`` by ``mycelium adapter add
hermes`` and loaded by hermes itself. From the mycelium-cli test suite
the plugin isn't on ``sys.path`` and the package name (``mycelium``)
would collide with our own top-level package if it were, so we load
``route.py`` and ``mentions.py`` via :mod:`importlib.util` under
synthetic names and exercise the pure formatters directly.

The intent here is mirror-test the openclaw ``route.test.ts`` so a
backend schema change that requires updating one formatter also needs
the snapshot here updated — the two stay in lockstep by construction.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── plugin-loader fixture ───────────────────────────────────────────────────

_PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mycelium"
    / "integrations"
    / "hermes"
    / "assets"
    / "mycelium"
    / "plugin"
)

# Synthetic package name keeps the assets out of ``mycelium.*`` so we
# don't shadow our own runtime imports during test collection.
_PKG_NAME = "_hermes_plugin_under_test"


def _load_plugin_modules():
    """Import ``route`` and ``mentions`` from the asset tree.

    Idempotent: re-using the same synthetic package name across tests
    means subsequent calls hit ``sys.modules``. We have to install a
    synthetic *package* (not just a module) because ``route.py`` does
    ``from .mentions import resolve_mentions``.
    """
    if _PKG_NAME in sys.modules:
        return sys.modules[_PKG_NAME + ".route"], sys.modules[_PKG_NAME + ".mentions"]

    pkg_spec = importlib.util.spec_from_file_location(
        _PKG_NAME,
        _PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_ROOT)],
    )
    assert pkg_spec is not None
    pkg_module = importlib.util.module_from_spec(pkg_spec)
    # Don't exec the plugin's real __init__ — it pulls in hermes-only
    # ``gateway.platforms.base`` through ``adapter.py``. We only need the
    # package skeleton for relative imports.
    sys.modules[_PKG_NAME] = pkg_module
    pkg_module.__path__ = [str(_PLUGIN_ROOT)]

    for sub in ("mentions", "route"):
        spec = importlib.util.spec_from_file_location(
            f"{_PKG_NAME}.{sub}",
            _PLUGIN_ROOT / f"{sub}.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG_NAME}.{sub}"] = module
        spec.loader.exec_module(module)

    return sys.modules[_PKG_NAME + ".route"], sys.modules[_PKG_NAME + ".mentions"]


@pytest.fixture(scope="module")
def route_module():
    route, _mentions = _load_plugin_modules()
    return route


@pytest.fixture(scope="module")
def mentions_module():
    _route, mentions = _load_plugin_modules()
    return mentions


# ── tick formatter ──────────────────────────────────────────────────────────


def test_format_tick_instruction_normal(route_module) -> None:
    """A normal tick renders round header, action, current offer, and the
    accept/reject commands at minimum. We assert on stable substrings
    rather than the whole rendering so cosmetic changes don't churn the
    test — but the substring set must be load-bearing enough that a
    silent payload drop fails the test."""
    tick = {
        "payload": {
            "participant_id": "alice",
            "round": 2,
            "n_steps_total": 5,
            "action": "respond",
            "can_counter_offer": True,
            "current_offer": {"api_style": "REST", "timeline": "Q1"},
            "your_last_action": "reject",
            "prior_round_outcome": "rejected_by_bob",
        }
    }
    out = route_module.format_tick_instruction(tick, "demo", "alice")
    assert "[CognitiveEngine — Round 2 of 5]" in out
    assert "structured negotiation in room demo" in out
    # The handle is folded into the header line so the agent knows which
    # ``--handle`` to use in any CLI command it issues during the round.
    assert "You are @alice" in out
    assert "Action required: respond" in out
    assert "You CAN propose a counter-offer." in out
    assert "Current offer on the table:" in out
    assert "  api_style: REST" in out
    assert "  timeline: Q1" in out
    assert 'Valid offer keys (use exactly these in your counter): "api_style", "timeline"' in out
    assert "mycelium negotiate propose" in out
    assert "--room demo --handle alice" in out
    # prior-round context shows who rejected (not the participant id again).
    assert "Last round: bob rejected the standing offer." in out
    assert "Your last action: reject." in out


def test_format_tick_instruction_accept_only_no_counter_line(route_module) -> None:
    """``can_counter_offer=False`` removes the counter command and the
    "valid offer keys" line, keeping accept/reject. This matches openclaw."""
    tick = {
        "payload": {
            "participant_id": "alice",
            "round": 1,
            "action": "respond",
            "can_counter_offer": False,
            "current_offer": {"timeline": "Q1"},
        }
    }
    out = route_module.format_tick_instruction(tick, "demo", "alice")
    assert "You can only accept or reject." in out
    assert "Valid offer keys" not in out
    assert "mycelium negotiate propose" not in out
    assert "mycelium negotiate respond accept --room demo --handle alice" in out
    assert "mycelium negotiate respond reject --room demo --handle alice" in out


def test_format_tick_instruction_first_round_no_outcome(route_module) -> None:
    """``first_round`` suppresses the prior-outcome line."""
    tick = {
        "payload": {
            "participant_id": "alice",
            "round": 1,
            "action": "propose",
            "can_counter_offer": True,
            "current_offer": {},
            "prior_round_outcome": "first_round",
        }
    }
    out = route_module.format_tick_instruction(tick, "demo", "alice")
    assert "Last round" not in out


def test_format_tick_instruction_shared_context_files(route_module) -> None:
    """``shared_context_files`` are included verbatim so every agent sees them."""
    tick = {
        "payload": {
            "participant_id": "alice",
            "round": 1,
            "action": "respond",
            "can_counter_offer": False,
            "current_offer": {},
            "shared_context_files": [
                {"path": "spec.md", "shared_by": "bob", "content": "# spec body\n"}
            ],
        }
    }
    out = route_module.format_tick_instruction(tick, "demo", "alice")
    assert "Shared context files (opt-in by participants):" in out
    assert "--- spec.md (shared by bob) ---" in out
    assert "# spec body" in out
    assert "--- end ---" in out


def test_format_tick_instruction_error_invalid_keys(route_module) -> None:
    """Error ticks with ``counter_offer_invalid_keys`` must surface the valid
    keys and a recovery command — without them the agent can't recover."""
    tick = {
        "error": "counter_offer_invalid_keys",
        "instruction": "Your counter-offer used unknown keys.",
        "valid_keys": ["api_style", "timeline"],
        "bad_keys": ["apistyle"],
        "payload": {"participant_id": "alice"},
    }
    out = route_module.format_tick_instruction(tick, "demo", "alice")
    assert "[CognitiveEngine — error: counter_offer_invalid_keys]" in out
    # Error ticks also surface the agent's handle so the recovery commands
    # below are unambiguous.
    assert "You are @alice in room demo." in out
    assert 'Rejected keys: "apistyle"' in out
    assert 'Valid keys (use exactly these): "api_style", "timeline"' in out
    assert (
        "Recovery: mycelium negotiate propose "
        '"api_style"=VALUE "timeline"=VALUE --room demo --handle alice' in out
    )


def test_format_tick_instruction_error_not_your_turn(route_module) -> None:
    """``counter_offer_not_your_turn`` recovery — accept or reject."""
    tick = {
        "error": "counter_offer_not_your_turn",
        "instruction": "It is not your turn to counter-offer.",
        "payload": {"participant_id": "alice"},
    }
    out = route_module.format_tick_instruction(tick, "demo", "alice")
    assert "Recovery: mycelium negotiate respond accept --room demo --handle alice" in out
    assert "or: mycelium negotiate respond reject --room demo --handle alice" in out


# ── consensus formatter ──────────────────────────────────────────────────────


def test_format_consensus_summary_agreement(route_module) -> None:
    summary = route_module.format_consensus_summary(
        {
            "plan": "ship REST in Q1",
            "assignments": {"alice": "build endpoints", "bob": "write tests"},
            "plan_file": "plan/tasks.md",
        }
    )
    assert "[CognitiveEngine — Consensus Reached!]" in summary
    assert "ship REST in Q1" in summary
    assert "  alice: build endpoints" in summary
    assert "  bob: write tests" in summary
    # plan_file should produce the "shared plan" pointer.
    assert "The consensus is now the room's shared plan (`plan/tasks.md`)." in summary
    assert "mycelium plan tasks" in summary


def test_format_consensus_summary_broken(route_module) -> None:
    summary = route_module.format_consensus_summary(
        {"broken": True, "plan": "Negotiation ended: timeout"}
    )
    assert "[CognitiveEngine — Negotiation FAILED]" in summary
    assert "Negotiation ended: timeout" in summary
    # Broken summaries don't include assignments or plan-file pointer.
    assert "Assignments:" not in summary
    assert "shared plan" not in summary


def test_format_consensus_summary_no_plan_file(route_module) -> None:
    """Older backends may not include ``plan_file`` — formatter must skip
    the "shared plan" stanza cleanly."""
    summary = route_module.format_consensus_summary(
        {"plan": "go with REST", "assignments": {"alice": "ship"}}
    )
    assert "shared plan" not in summary
    assert "  alice: ship" in summary


# ── route_message dispatch decisions ────────────────────────────────────────


def test_route_message_skips_own_messages(route_module) -> None:
    cfg = route_module.RoomConfig(room="demo", agents=("alice",), require_mention=True)
    own_ids = {"m1"}
    actions = route_module.route_message(cfg, {"id": "m1", "content": "x"}, own_ids)
    assert len(actions) == 1
    assert isinstance(actions[0], route_module.Ignore)
    assert "own message" in actions[0].reason
    # The id is consumed (matches the openclaw .delete() side effect).
    assert "m1" not in own_ids


def test_route_message_tick_dispatches_to_target(route_module) -> None:
    cfg = route_module.RoomConfig(room="demo", agents=("alice", "bob"), require_mention=True)
    msg = {
        "id": "m1",
        "room_name": "demo",
        "message_type": "coordination_tick",
        "content": '{"payload": {"participant_id": "alice", "round": 1, "action": "respond", '
        '"can_counter_offer": false, "current_offer": {}}}',
    }
    actions = route_module.route_message(cfg, msg, set())
    dispatches = [a for a in actions if isinstance(a, route_module.Dispatch)]
    assert len(dispatches) == 1
    assert dispatches[0].agent_id == "alice"
    assert dispatches[0].sender == "CognitiveEngine"
    assert "structured negotiation in room demo" in dispatches[0].content


def test_route_message_tick_for_non_member_is_ignored(route_module) -> None:
    cfg = route_module.RoomConfig(room="demo", agents=("alice",), require_mention=True)
    msg = {
        "id": "m1",
        "room_name": "demo",
        "message_type": "coordination_tick",
        "content": '{"payload": {"participant_id": "carol", "round": 1, '
        '"current_offer": {}, "action": "respond", "can_counter_offer": false}}',
    }
    actions = route_module.route_message(cfg, msg, set())
    assert all(isinstance(a, route_module.Ignore) for a in actions)


def test_route_message_consensus_fans_out(route_module) -> None:
    cfg = route_module.RoomConfig(room="demo", agents=("alice", "bob"), require_mention=True)
    msg = {
        "id": "c1",
        "room_name": "demo:session:42",
        "message_type": "coordination_consensus",
        "content": '{"plan": "do it", "assignments": {"alice": "ship"}, "plan_file": "plan/tasks.md"}',
    }
    actions = route_module.route_message(cfg, msg, set())
    dispatches = [a for a in actions if isinstance(a, route_module.Dispatch)]
    assert {d.agent_id for d in dispatches} == {"alice", "bob"}
    # Each recipient's content gets a personalized identity preamble.
    by_agent = {d.agent_id: d.content for d in dispatches}
    assert by_agent["alice"].startswith(
        "[mycelium-room] You are @alice in room demo:session:42.\n\n"
    )
    assert by_agent["bob"].startswith("[mycelium-room] You are @bob in room demo:session:42.\n\n")
    # The consensus summary itself is still in the content (preserved
    # after the preamble).
    assert "shared plan" in by_agent["alice"]
    notify = [a for a in actions if isinstance(a, route_module.NotifyHome)]
    assert len(notify) == 1
    assert notify[0].session_room == "demo:session:42"
    assert set(notify[0].agent_ids) == {"alice", "bob"}
    assert "shared plan" in notify[0].consensus_summary
    # NotifyHome carries the un-prefixed summary because the home-channel
    # delivery is for the human user, not for the hermes agent loop.
    assert not notify[0].consensus_summary.startswith("[mycelium-room]")


def test_route_message_consensus_in_parent_does_not_notify_home(route_module) -> None:
    """Consensus messages that land in the parent room (no ``:session:`` in
    room_name) skip notify-home — there is no cross-channel hop to bridge."""
    cfg = route_module.RoomConfig(room="demo", agents=("alice",), require_mention=True)
    msg = {
        "id": "c1",
        "room_name": "demo",  # not a session sub-room
        "message_type": "coordination_consensus",
        "content": '{"plan": "do it", "assignments": {"alice": "ship"}}',
    }
    actions = route_module.route_message(cfg, msg, set())
    assert not any(isinstance(a, route_module.NotifyHome) for a in actions)


def test_route_message_join_subscribes_session_room(route_module) -> None:
    cfg = route_module.RoomConfig(room="demo", agents=("alice",), require_mention=True)
    msg = {
        "id": "j1",
        "room_name": "demo:session:42",
        "message_type": "coordination_join",
        "sender_handle": "alice",
    }
    actions = route_module.route_message(cfg, msg, set())
    subs = [a for a in actions if isinstance(a, route_module.SubscribeSession)]
    stashes = [a for a in actions if isinstance(a, route_module.StashReturnAddress)]
    assert len(subs) == 1
    assert subs[0].room_name == "demo:session:42"
    assert len(stashes) == 1
    assert stashes[0].agent_id == "alice"


def test_route_message_broadcast_require_mention_gates(route_module) -> None:
    """With require_mention=True, broadcasts without an @-mention are
    ignored, mirroring openclaw's defaults."""
    cfg = route_module.RoomConfig(room="demo", agents=("alice", "bob"), require_mention=True)
    msg = {
        "id": "b1",
        "room_name": "demo",
        "message_type": "broadcast",
        "sender_handle": "carol",
        "content": "fyi the deployment is done",
    }
    actions = route_module.route_message(cfg, msg, set())
    assert all(isinstance(a, route_module.Ignore) for a in actions)

    msg["content"] = "@alice the deployment is done"
    actions = route_module.route_message(cfg, msg, set())
    dispatches = [a for a in actions if isinstance(a, route_module.Dispatch)]
    assert [d.agent_id for d in dispatches] == ["alice"]
    # Identity preamble is prepended so the agent knows what handle to use
    # in any CLI command it issues in response.
    assert dispatches[0].content.startswith("[mycelium-room] You are @alice in room demo.\n\n")
    assert dispatches[0].content.endswith("@alice the deployment is done")


def test_route_message_broadcast_open_mode_excludes_sender(route_module) -> None:
    """With require_mention=False, broadcasts fan out to *all* agents
    except the sender (no self-DM)."""
    cfg = route_module.RoomConfig(room="demo", agents=("alice", "bob"), require_mention=False)
    msg = {
        "id": "b1",
        "room_name": "demo",
        "message_type": "broadcast",
        "sender_handle": "alice",
        "content": "team status: done",
    }
    actions = route_module.route_message(cfg, msg, set())
    dispatches = [a for a in actions if isinstance(a, route_module.Dispatch)]
    assert [d.agent_id for d in dispatches] == ["bob"]
    # Open mode still personalizes the dispatch per recipient.
    assert dispatches[0].content.startswith("[mycelium-room] You are @bob in room demo.\n\n")


# ── mentions ────────────────────────────────────────────────────────────────


def test_resolve_mentions_basic(mentions_module) -> None:
    assert mentions_module.resolve_mentions("@alice hi", ["alice", "bob"]) == ["alice"]
    assert mentions_module.resolve_mentions("hi @alice and @bob", ["alice", "bob"]) == [
        "alice",
        "bob",
    ]


def test_resolve_mentions_word_boundary(mentions_module) -> None:
    # ``@julia-agent-bot`` must NOT match ``julia-agent``.
    assert mentions_module.resolve_mentions("@julia-agent-bot hi", ["julia-agent"]) == []
    # Case-insensitive match keeps the persisted lowercase handle.
    assert mentions_module.resolve_mentions("@Alice hello", ["alice"]) == ["alice"]


def test_resolve_mentions_no_at_prefix(mentions_module) -> None:
    # Bare handles (no @) don't trigger.
    assert mentions_module.resolve_mentions("alice hi", ["alice"]) == []
