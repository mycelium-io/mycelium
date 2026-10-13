# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A herdr server left running from before the app was updated.

macOS can refuse such a server, and every terminal in it, access to folders
like ~/Documents. These hold how it's found (its program file written after
it started), that the app is asked once per server and herdr restarts only on
a yes, and what the health check and ``mycelium desktop restart-herdr`` say.
Nothing here touches the herdr running on this machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium.desktop import checks, herdr_server
from mycelium.desktop import supervisor as sv
from mycelium.desktop.herdr_server import Server
from mycelium.desktop.supervisor import Component, Locator, Supervisor
from mycelium.runner import approvals

PS = """\
  501 Sun Oct  4 00:54:23 2026     herdr
24611 Sun Oct  4 00:54:23 2026     /Applications/Mycelium.app/Contents/MacOS/herdr server
  777 Mon Oct  5 09:00:00 2026     /Users/a b/bin/herdr server
  778 Mon Oct  5 09:00:00 2026     /usr/bin/python3 server
"""


def test_the_server_is_read_from_ps_and_the_client_is_not():
    servers = herdr_server.parse_ps(PS)
    assert [(s.pid, str(s.program)) for s in servers] == [
        (24611, "/Applications/Mycelium.app/Contents/MacOS/herdr"),
        (777, "/Users/a b/bin/herdr"),
    ]
    started = time.localtime(servers[0].started)
    assert (started.tm_mon, started.tm_mday, started.tm_hour) == (10, 4, 0)


def test_a_program_written_after_the_server_started_is_replaced(tmp_path: Path):
    program = tmp_path / "herdr"
    program.write_text("")
    written = program.stat().st_ctime
    assert Server(1, program, started=written + 60).replaced_at() is None
    assert Server(1, program, started=written - 3600).replaced_at() is not None
    # Gone altogether counts as replaced too.
    assert Server(1, tmp_path / "gone", started=written).replaced_at() is not None


def test_what_happens_to_agents_depends_on_herdrs_integrations(monkeypatch):
    from mycelium import machine

    def state(current: dict[str, bool]) -> Any:
        return machine.Integrations("0.9.3", "0.9.3", False, False, current, None)

    monkeypatch.setattr(machine, "integrations", lambda: state({"claude": True}))
    assert "brings each one back" in herdr_server.agents_after_restart()
    monkeypatch.setattr(machine, "integrations", lambda: state({"claude": False}))
    said = herdr_server.agents_after_restart()
    assert "(claude)" in said
    assert "mycelium machine restart" in said


# ── the supervisor ──────────────────────────────────────────────────────────


class Events(list):
    def __call__(self, event: dict[str, Any]) -> None:
        self.append(event)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self if e["type"] == kind]


APP_HERDR = ["/Applications/Mycelium.app/Contents/MacOS/herdr", "server"]


class AppLocator(Locator):
    def herdr(self) -> list[str]:
        return APP_HERDR


def _supervisor(tmp_path: Path, found: list[Server | None], restarted: list) -> tuple:
    events = Events()
    sup = Supervisor(
        "client",
        hub_url="http://hub.example",
        emit=events,
        env={},
        start_runner=False,
        locator=AppLocator(None, None),
        stale_herdr=lambda: found[-1],
        restart_herdr=lambda server, argv: restarted.append((server.pid, argv)),
        requests_base=tmp_path,
    )
    herdr = Component(name="herdr", argv=lambda: ([], None), ready=lambda: True, state="running")
    sup.components = [herdr]
    return sup, events


def _answer(tmp_path: Path, events: Events, *, yes: bool) -> None:
    (request,) = [e["request"] for e in events.of("request")]
    assert request["title"] == "Restart herdr?"
    assert (request["yes"], request["no"]) == ("Restart herdr", "Not now")
    approvals.answer(request["id"], yes=yes, base=tmp_path)


def _settle(cond, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cond():
        time.sleep(0.02)
    assert cond()


def test_a_stale_server_is_reported_and_restarted_on_a_yes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(approvals, "CHECK_S", 0.01)
    program = tmp_path / "herdr"
    program.write_text("")
    server = Server(42, program, started=program.stat().st_ctime - 3600)
    restarted: list = []
    sup, events = _supervisor(tmp_path, [server], restarted)

    sup._watch_herdr(now=1.0)
    status = sup.status()
    assert status["stale_herdr"]["pid"] == 42
    assert sv.STALE_HERDR_WARNING in status["warnings"]
    assert "Operation not permitted" in sv.STALE_HERDR_WARNING

    _answer(tmp_path, events, yes=True)
    _settle(lambda: restarted)
    assert restarted == [(42, APP_HERDR)]


def test_herdr_is_left_alone_on_a_no_and_each_server_is_asked_once(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "CHECK_S", 0.01)
    program = tmp_path / "herdr"
    program.write_text("")
    found: list[Server | None] = [Server(42, program, started=program.stat().st_ctime - 3600)]
    restarted: list = []
    sup, events = _supervisor(tmp_path, found, restarted)

    sup._watch_herdr(now=1.0)
    _answer(tmp_path, events, yes=False)
    _settle(lambda: not list((tmp_path / "requests").glob("*.json")))
    # A minute later it's still stale, and still reported, but not asked again.
    sup._watch_herdr(now=1.0 + sv.HERDR_CHECK_S)
    assert len(events.of("request")) == 1
    assert restarted == []
    assert sup.status()["stale_herdr"] is not None
    # Once it's restarted some other way, the warning clears.
    found.append(None)
    sup._watch_herdr(now=1.0 + 2 * sv.HERDR_CHECK_S)
    assert sup.status()["stale_herdr"] is None
    assert sv.STALE_HERDR_WARNING not in sup.status()["warnings"]


def test_nothing_is_checked_until_herdr_is_running(tmp_path: Path):
    asked: list = []
    sup, _events = _supervisor(tmp_path, [None], [])
    sup.find_stale_herdr = lambda: asked.append(1)
    sup.components[0].state = "starting"
    sup._watch_herdr(now=1.0)
    assert asked == []


# ── restarting ──────────────────────────────────────────────────────────────


def test_restart_stops_the_old_server_and_starts_the_new_one(tmp_path: Path, monkeypatch):
    from mycelium.integrations.herdr import HerdrBridge

    monkeypatch.setattr(herdr_server, "LOG_PATH", tmp_path / "herdr.log")
    monkeypatch.setattr(HerdrBridge, "available", lambda _self: True)
    # A program whose `server stop` does nothing, so the old one has to be signalled.
    program = tmp_path / "herdr"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o755)
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    reaper = threading.Thread(target=old.wait, daemon=True)
    reaper.start()
    marker = tmp_path / "started"
    start = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"]

    herdr_server.restart(Server(old.pid, program, started=0.0), start, timeout=5)

    reaper.join(timeout=5)
    assert old.poll() is not None
    _settle(marker.exists)


def test_a_server_that_wont_stop_is_said(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(herdr_server, "_alive", lambda _pid: True)
    monkeypatch.setattr(os, "kill", lambda *_a: None)
    with pytest.raises(herdr_server.RestartError, match="didn't stop"):
        herdr_server.restart(Server(1, tmp_path / "herdr", 0.0), ["true"], timeout=0.1)


# ── the health check and the command ────────────────────────────────────────


def test_the_health_check_warns_and_says_how_to_restart(monkeypatch, tmp_path: Path):
    from mycelium.integrations.herdr import HerdrBridge

    for name, value in (("binary_present", True), ("available", True)):
        monkeypatch.setattr(HerdrBridge, name, lambda _self, v=value: v)
    monkeypatch.setattr(HerdrBridge, "server_version", lambda _self: "0.9.3")
    monkeypatch.setattr(HerdrBridge, "version", lambda _self: "0.9.3")
    monkeypatch.setattr(herdr_server, "stale", lambda: Server(1, tmp_path / "herdr", 0.0))
    monkeypatch.setattr(herdr_server, "agents_after_restart", lambda: "agents line")
    result = checks.herdr()
    assert result.status == "warning"
    assert result.message == "running from before Mycelium was updated"
    assert result.details[-1] == "Restart it with `mycelium desktop restart-herdr`."


def test_the_command_restarts_only_a_stale_server(monkeypatch, tmp_path: Path):
    from mycelium.cli import app

    restarted: list = []
    monkeypatch.setattr(herdr_server, "restart", lambda server, argv: restarted.append(argv))
    monkeypatch.setattr(herdr_server, "agents_after_restart", lambda: "agents line")
    monkeypatch.setattr(Locator, "herdr", lambda _self: ["/x/herdr", "server"])

    monkeypatch.setattr(herdr_server, "stale", lambda: None)
    result = CliRunner().invoke(app, ["desktop", "restart-herdr", "--yes"])
    assert result.exit_code == 0
    assert restarted == []

    monkeypatch.setattr(herdr_server, "stale", lambda: Server(1, tmp_path / "herdr", 0.0))
    result = CliRunner().invoke(app, ["desktop", "restart-herdr", "--yes"])
    assert result.exit_code == 0, result.output
    assert restarted == [["/x/herdr", "server"]]
