# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An ``@!handle`` mention: stop a working agent's turn so it reads the message now.

Covers what keeps it safe: only someone allowed, only a working agent, only
through the runner on the agent's machine, and an ordinary mention otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import settings
from app.schemas import RunnerAgentRead, RunnerHello
from app.services import (
    asks,
    interrupts,
    message_format,
    principals,
    room_channels,
    turns,
    wake_digest,
)
from app.services.message_models import Kind
from app.services.message_slim import serialize_content
from app.services.runners import RunnerRegistry
from app.services.worker_engine import keep_team_mentions
from tests.fakes import FakeSlimClient

ROOM = "room-a"
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> room_channels.RoomChannelManager:
    monkeypatch.setattr(settings, "SLIM_ENABLED", True)
    monkeypatch.setattr(room_channels, "node_reachable", lambda _endpoint: True)
    monkeypatch.setattr(room_channels, "SlimClient", FakeSlimClient)
    monkeypatch.setattr(room_channels.RoomChannelManager, "_start_persister", lambda self, m: None)
    return room_channels.RoomChannelManager(endpoint="http://node", default_workspace="ws")


@pytest.fixture
def runners(monkeypatch: pytest.MonkeyPatch) -> RunnerRegistry:
    """A registry with one connected machine running @coder in a herdr pane, and
    the room's members: @julia is a person, @scout is another agent, and
    @aligner is an engine."""
    registry = RunnerRegistry()
    registry.hello(
        RunnerHello(
            id="mac",
            label="Julia's Mac",
            agents=[
                RunnerAgentRead(
                    handle="coder",
                    room=ROOM,
                    framework="claude",
                    status="running",
                    pane="w1:p2",
                    started_at=NOW,
                )
            ],
        )
    )
    monkeypatch.setattr(interrupts, "registry", registry)
    kinds = {"coder": "agent", "scout": "agent", "aligner": "engine"}
    monkeypatch.setattr(principals, "classify_sender", lambda _room, h: kinds.get(h, "user"))
    return registry


def _jobs(registry: RunnerRegistry) -> list[tuple[str, dict]]:
    return [(j.kind, j.spec) for j in registry.jobs("mac") or []]


def _say(manager: room_channels.RoomChannelManager, text: str, sender: str) -> list[str]:
    """``sender`` posts ``text`` in the room: each handle it asks goes through
    the hook every recorded message does. Returns the handles rung."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.live_episode_urn(ROOM),
        sender=sender,
        topic=message_format.topic_urn(ROOM),
        payload_type="message",
    )
    hook = manager._asked_adapter(ROOM)
    asked = asks.asked(serialize_content(env, extra={"content": text}), ROOM)
    for handle, why in asked.items():
        hook(handle, why, env, text)
    return [h for h in asked if manager.herdr_status(ROOM, h) is not None]


def test_a_person_interrupts_a_working_agent(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    woke = _say(manager, "@!coder stop, you're in the wrong checkout", "julia")
    assert woke == ["coder"]
    assert _jobs(runners) == [("interrupt", {"room": ROOM, "handle": "coder", "pane": "w1:p2"})]
    # The wake is held while it works, and says it was an interrupt once it's idle.
    assert manager.drain_herdr_wakes(ROOM) == []
    manager.set_herdr_presence(ROOM, {"coder": "idle"})
    (wake,) = manager.drain_herdr_wakes(ROOM)
    assert wake["reason"] == "interrupt"
    assert wake["from"] == "julia"


def test_an_idle_agent_gets_an_ordinary_mention(manager, runners):
    # The key on an idle session could clear what a person was typing there.
    manager.set_herdr_presence(ROOM, {"coder": "idle"})
    _say(manager, "@!coder when you can", "julia")
    assert _jobs(runners) == []
    (wake,) = manager.drain_herdr_wakes(ROOM)
    assert wake["reason"] == "mention"


def test_any_agent_in_the_room_may_interrupt_another(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    _say(manager, "@!coder hold on, that's main", "scout")
    assert [k for k, _ in _jobs(runners)] == ["interrupt"]
    assert manager._herdr_wakes[ROOM][0]["reason"] == "interrupt"
    assert interrupts.refusal(ROOM, "coder", "scout") is None


def test_an_engine_never_interrupts(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    _say(manager, "@!coder your turn", "aligner")
    assert _jobs(runners) == []
    assert manager._herdr_wakes[ROOM][0]["reason"] == "mention"
    assert "engine" in (interrupts.refusal(ROOM, "coder", "aligner") or "")


def test_an_agent_no_runner_reports_gets_an_ordinary_mention(manager, runners):
    manager.set_herdr_presence(ROOM, {"stranger": "working"})
    _say(manager, "@!stranger stop", "julia")
    assert _jobs(runners) == []
    assert manager._herdr_wakes[ROOM][0]["reason"] == "mention"


def test_a_later_mention_or_turn_does_not_downgrade_an_interrupt(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    _say(manager, "@!coder stop", "julia")
    _say(manager, "@coder also this", "scout")
    manager.enqueue_herdr_wake(ROOM, "coder", reason="turn")
    assert manager._herdr_wakes[ROOM][0]["reason"] == "interrupt"


def test_the_digest_says_it_was_interrupted_and_to_carry_on():
    digest = wake_digest.build(
        ROOM, {"handle": "coder", "reason": "interrupt", "from": "julia"}, [], NOW
    )
    assert digest.splitlines()[2] == (
        "Why:     @julia sent you an urgent message with @! in the room (room-a), which stops "
        "your turn if you were working. Read it and act on it, then carry on with what you "
        "were doing unless it says otherwise."
    )


def test_hub_run_members_can_never_interrupt():
    # A persona's text loses every sigil; a worker keeps a teammate's mention
    # as a plain @, never an @!.
    assert turns.neutralize_mentions("@!coder stop and ask @lead") == "coder stop and ask lead"
    assert keep_team_mentions("@!coder stop, @!aligner", ["coder"], "me") == "@coder stop, aligner"
