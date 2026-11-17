# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Stopping agents to free memory, starting them again, and keeping some
running: ``mycelium agent stop|start|keep``. The hub is a stand-in at httpx's
transport, answering in the shapes it really sends."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from tests.conftest import StandInHub, install_stand_in_hub

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "eng")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "julia")
    for name in ("MYCELIUM_API_URL", "HERDR_PANE_ID", "HERDR_SOCKET_PATH"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> StandInHub:
    return install_stand_in_hub(monkeypatch)


def _row(handle: str, state: str, **over) -> dict:
    return {
        "room": "eng",
        "handle": handle,
        "owner": "julia",
        "state": state,
        "runner": "mac",
        "machine": "Julia's computer",
        **over,
    }


def _controlled(request: httpx.Request) -> dict:
    handle = request.url.path.split("/")[-2]
    return {"room": "eng", "handle": handle, "runner": "mac", "job": "ab12"}


def test_stop_idle_stops_idle_and_paused_agents_but_never_kept_ones(hub: StandInHub, tmp_path):
    running = {
        "agents": [
            _row("busy", "working"),
            _row("napping", "idle"),
            _row("paused", "paused"),
            _row("asking", "blocked"),
            _row("pinned", "idle", keep=True),
            _row("done", "stopped"),
            _row("elsewhere", "idle", machine="morgan-mini"),
        ]
    }
    hub.answer = lambda r: running if r.method == "GET" else _controlled(r)
    # What the runner here wrote: numbers for this machine's agents only.
    usage = tmp_path / ".mycelium" / "runner" / "usage.json"
    usage.parent.mkdir(parents=True)
    usage.write_text(json.dumps({"agents": [{"room": "eng", "handle": "napping", "ram_mb": 1200}]}))

    result = runner.invoke(app, ["agent", "stop", "--idle", "--yes"])

    assert result.exit_code == 0, result.output
    (asked,) = hub.sent("GET", "/api/agents/running")
    assert asked.url.params["owner"] == "julia"
    stopped = [r.url.path.split("/")[-2] for r in hub.requests if r.method == "POST"]
    # Not one waiting on a person to answer it.
    assert stopped == ["napping", "paused", "elsewhere"]
    for request in hub.requests[1:]:
        assert json.loads(request.content) == {"by": "julia", "close": False}
    out = " ".join(result.output.split())
    assert "@napping in eng on Julia's computer 1.2 GB" in out
    assert "Stopping them frees about 1.2 GB on this computer." in out
    assert "Kept running: @pinned" in out


def test_stop_idle_with_nothing_idle_stops_nothing_and_names_the_kept(hub: StandInHub):
    agents = [_row("busy", "working"), _row("pinned", "idle", keep=True)]
    hub.answer = lambda _r: {"agents": agents}
    result = runner.invoke(app, ["agent", "stop", "--idle", "--yes"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "Nothing to stop" in out
    # A kept agent idle is why, so it's named.
    assert "Kept running: @pinned" in out
    assert [r for r in hub.requests if r.method == "POST"] == []


def test_stop_names_one_agent_or_idle_not_both(hub: StandInHub):
    assert runner.invoke(app, ["agent", "stop", "scout", "--idle"]).exit_code == 2
    assert runner.invoke(app, ["agent", "stop"]).exit_code == 2
    assert hub.requests == []


def test_a_stop_keeps_the_pane_and_says_how_to_start_it(hub: StandInHub):
    hub.answer = _controlled
    result = runner.invoke(app, ["agent", "stop", "scout", "--yes"])
    assert result.exit_code == 0, result.output
    (sent,) = hub.sent("POST", "/api/rooms/eng/agents/scout/stop")
    assert json.loads(sent.content) == {"by": "julia", "close": False}
    out = " ".join(result.output.split())
    assert "its pane stays for a start" in out
    assert "mycelium agent start scout --room eng" in out

    closed = runner.invoke(app, ["agent", "stop", "scout", "--close", "--yes"])
    assert closed.exit_code == 0, closed.output
    assert json.loads(hub.sent("POST", "/api/rooms/eng/agents/scout/stop")[1].content)["close"]
    assert "its pane is closed" in closed.output


def test_start_asks_the_hub_and_says_the_machine_asks_first(hub: StandInHub):
    hub.answer = _controlled
    result = runner.invoke(app, ["agent", "start", "scout"])
    assert result.exit_code == 0, result.output
    assert hub.sent("POST", "/api/rooms/eng/agents/scout/start")
    assert "mycelium runner approve ab12" in " ".join(result.output.split())


def test_keep_and_keep_off(hub: StandInHub):
    hub.answer = lambda r: {
        "room": "eng",
        "handle": "scout",
        "keep": json.loads(r.content)["keep"],
    }
    on = runner.invoke(app, ["agent", "keep", "scout"])
    assert on.exit_code == 0, on.output
    assert "Keeping @scout running" in on.output
    off = runner.invoke(app, ["agent", "keep", "scout", "--off"])
    assert "no longer kept running" in off.output
    sent = [json.loads(r.content) for r in hub.sent("POST", "/api/rooms/eng/agents/scout/keep")]
    assert sent == [{"by": "julia", "keep": True}, {"by": "julia", "keep": False}]
