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
from app.services import interrupts, principals, room_channels, turns, wake_digest
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
    the room's people and agents: @julia is a person, @lead leads @coder, @scout
    is an agent that doesn't."""
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
    agents = {"coder", "lead", "scout"}
    monkeypatch.setattr(
        principals, "classify_sender", lambda _room, h: "agent" if h in agents else "user"
    )
    monkeypatch.setattr(
        principals,
        "delegates_to",
        lambda _room, target, actor: (target, actor) == ("coder", "lead"),
    )
    return registry


def _jobs(registry: RunnerRegistry) -> list[tuple[str, dict]]:
    return [(j.kind, j.spec) for j in registry.jobs("mac") or []]


def test_a_person_interrupts_a_working_agent(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    woke = manager.enqueue_herdr_wakes_for_mentions(
        ROOM, "@!coder stop, you're in the wrong checkout", sender="julia"
    )
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
    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@!coder when you can", sender="julia")
    assert _jobs(runners) == []
    (wake,) = manager.drain_herdr_wakes(ROOM)
    assert wake["reason"] == "mention"


def test_only_its_lead_among_agents_may_interrupt_it(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@!coder hold on", sender="scout")
    assert _jobs(runners) == []
    assert manager._herdr_wakes[ROOM][0]["reason"] == "mention"

    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@!coder hold on", sender="lead")
    assert [k for k, _ in _jobs(runners)] == ["interrupt"]
    assert manager._herdr_wakes[ROOM][0]["reason"] == "interrupt"
    assert "allow_from" in (interrupts.refusal(ROOM, "coder", "scout") or "")


def test_an_agent_no_runner_reports_gets_an_ordinary_mention(manager, runners):
    manager.set_herdr_presence(ROOM, {"stranger": "working"})
    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@!stranger stop", sender="julia")
    assert _jobs(runners) == []
    assert manager._herdr_wakes[ROOM][0]["reason"] == "mention"


def test_a_later_mention_or_turn_does_not_downgrade_an_interrupt(manager, runners):
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@!coder stop", sender="julia")
    manager.enqueue_herdr_wakes_for_mentions(ROOM, "@coder also this", sender="scout")
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
