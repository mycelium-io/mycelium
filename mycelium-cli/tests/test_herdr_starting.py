# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Starting an agent CLI in a herdr pane: a slow shell is waited for, an exit is
said at once, and a start that keeps failing stops trying.

herdr is a stand-in bridge with only the calls a start makes.
"""

from __future__ import annotations

import threading
import time

import pytest

from mycelium.integrations.herdr import AgentExitedError, HerdrError, starting
from mycelium.integrations.herdr.bridge import NOT_A_SHELL


def test_an_agent_is_started_again_while_its_pane_comes_up(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(starting, "START_RETRY_S", 0)
    attempts: list[str] = []

    class _Bridge:
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            if len(attempts) < 2:
                raise HerdrError("pane is not at a shell prompt")
            return {}

        def get_agent(self, pane: str) -> dict | None:
            return None

    starting.start_when_ready(_Bridge(), "agent-1", "claude", "w9:p1", room="eng")
    assert attempts == ["w9:p1", "w9:p1"]

    attempts.clear()

    class _Never(_Bridge):
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            raise HerdrError("still not ready")

    with pytest.raises(HerdrError):
        starting.start_when_ready(_Never(), "agent-1", "claude", "w9:p1", room="eng")
    assert len(attempts) == starting.START_ATTEMPTS


def test_an_agent_cli_that_exits_while_herdr_waits_fails_at_once(monkeypatch: pytest.MonkeyPatch):
    """herdr waits out its whole timeout for an agent that exited; the pane says sooner."""
    monkeypatch.setattr(starting, "EXIT_POLL_S", 0.01)
    release = threading.Event()
    attempts: list[str] = []
    looks: list[str] = []

    class _Bridge:
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            release.wait(5)  # herdr, still waiting for an agent that has gone
            return {}

        def get_agent(self, pane: str) -> dict | None:
            looks.append(pane)
            # It came up for a moment, then exited back to the shell.
            return {"agent": "codex"} if len(looks) < 3 else None

    began = time.monotonic()
    try:
        with pytest.raises(AgentExitedError):
            starting.start_when_ready(_Bridge(), "agent-1", "codex", "w9:p1", room="eng")
    finally:
        release.set()
    assert time.monotonic() - began < 2
    assert attempts == ["w9:p1"]


def test_an_agent_cli_that_exits_before_it_is_ever_seen_fails_once_the_start_is_taken(
    monkeypatch: pytest.MonkeyPatch,
):
    """A CLI refusing its arguments exits in about 100ms, before the first look.
    herdr names an agent on the pane as soon as it takes a start, so a start in
    flight past the grace with nothing on the pane has exited."""
    monkeypatch.setattr(starting, "EXIT_POLL_S", 0.01)
    monkeypatch.setattr(starting, "EXIT_GRACE_S", 0.1)
    release = threading.Event()
    attempts: list[str] = []

    class _Bridge:
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            release.wait(5)
            return {}

        def get_agent(self, pane: str) -> dict | None:
            return None  # never there: it was gone before anyone looked

    began = time.monotonic()
    try:
        with pytest.raises(AgentExitedError):
            starting.start_when_ready(_Bridge(), "agent-1", "codex", "w9:p1", room="eng")
    finally:
        release.set()
    assert time.monotonic() - began < 2
    assert attempts == ["w9:p1"]


def test_herdr_saying_the_agent_exited_is_not_tried_again(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(starting, "START_RETRY_S", 0)
    attempts: list[str] = []

    class _Bridge:
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            raise HerdrError("agent process exited before becoming interactive")

        def get_agent(self, pane: str) -> dict | None:
            return None

    with pytest.raises(AgentExitedError):
        starting.start_when_ready(_Bridge(), "agent-1", "codex", "w9:p1", room="eng")
    assert attempts == ["w9:p1"]


def test_a_slow_shell_is_said_once_and_still_waited_for(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(starting, "START_RETRY_S", 0)
    monkeypatch.setattr(starting, "SLOW_SHELL_S", 0)
    told: list[str] = []
    attempts: list[str] = []

    class _Bridge:
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            if len(attempts) < 4:
                raise HerdrError(f"agent target pane {pane} is {NOT_A_SHELL}")
            return {}

        def get_agent(self, pane: str) -> dict | None:
            return None

        def read_pane(self, *_: object, **__: object) -> str:
            raise AssertionError("what a shell shows is never read for meaning")

    came_up = starting.start_when_ready(
        _Bridge(),
        "agent-1",
        "claude",
        "w9:p1",
        room="eng",
        on_slow_shell=lambda: told.append("slow"),
    )
    assert came_up is None
    assert told == ["slow"]
    assert len(attempts) == 4


def test_nothing_is_typed_until_the_agent_s_screen_has_drawn(monkeypatch: pytest.MonkeyPatch):
    """herdr reads an agent as ready before its screen takes input (OpenCode's);
    the wait goes on until the screen is drawn and stays the same."""
    monkeypatch.setattr(starting, "DRAW_POLL_S", 0)
    screens = iter([None, "", "loading", "input box", "input box", "input box", "unreached"])
    reads: list[str | None] = []

    class _Bridge:
        def read_pane(self, pane: str, **_: object) -> str | None:
            reads.append(screen := next(screens))
            return screen

    starting.wait_drawn(_Bridge(), "w9:p1", "opencode")
    assert reads == [None, "", "loading", "input box", "input box", "input box"]

    class _Unread:
        def read_pane(self, *_: object, **__: object) -> str:
            raise AssertionError("a CLI that takes input once herdr says so isn't read")

    starting.wait_drawn(_Unread(), "w9:p1", "claude")


def test_a_screen_that_never_settles_is_waited_for_only_so_long(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(starting, "DRAW_POLL_S", 0)
    monkeypatch.setattr(starting, "DRAW_WAIT_S", 0.05)
    ticks = iter(range(10**9))

    class _Bridge:
        def read_pane(self, pane: str, **_: object) -> str:
            return f"spinner {next(ticks)}"

    began = time.monotonic()
    starting.wait_drawn(_Bridge(), "w9:p1", "opencode")
    assert time.monotonic() - began < 1
