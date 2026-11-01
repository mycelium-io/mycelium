# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What one sync pass asks the hub: two calls a room on one connection, not a
call per agent on a new connection each, and nothing about a room the hub
doesn't have."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from typing import Any

import httpx
import pytest

from mycelium.commands import herdr
from mycelium.config import MyceliumConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping, HerdrRegistry


class Hub:
    def __init__(self, *, missing: tuple[str, ...] = ()) -> None:
        self.calls: Counter[str] = Counter()
        self.clients = 0
        self.credentials = 0
        self.missing = missing
        #: Rooms whose paths a proxy in front of the hub answers 404 for.
        self.unrouted: tuple[str, ...] = ()

    def handle(self, request: httpx.Request) -> httpx.Response:
        room = request.url.path.split("/")[3]
        self.calls[f"{request.method} {room} {request.url.path.rsplit('/', 1)[-1]}"] += 1
        if room in self.missing:
            return httpx.Response(404, json={"detail": "Room not found"})
        if room in self.unrouted:
            return httpx.Response(404, text="<html>Not Found</html>")
        if request.url.path.endswith("herdr-wakes"):
            return httpx.Response(200, json={"wakes": []})
        return httpx.Response(204)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Hub:
    hub = Hub()

    def client(_config: Any = None, **_kw: Any) -> httpx.Client:
        hub.clients += 1
        return httpx.Client(base_url="http://hub:8000", transport=httpx.MockTransport(hub.handle))

    def credential(_config: Any = None, **_kw: Any) -> dict[str, str]:
        hub.credentials += 1
        return {"Authorization": f"Bearer t{hub.credentials}"}

    monkeypatch.setattr("mycelium.client.hub_client", client)
    monkeypatch.setattr("mycelium.client.auth_headers", credential)
    monkeypatch.setattr(herdr, "sync_source", lambda: "laptop-1a2b")
    return hub


def _bridge(tmp_path: Any, rooms: int) -> tuple[HerdrBridge, list[tuple[str, str]]]:
    agents = []
    registry = HerdrRegistry(tmp_path / "herdr.json")
    targets = []
    for i in range(rooms):
        ws, room = f"w{i}", f"room-{i}"
        targets.append((ws, room))
        for j in range(2):
            pane = f"{ws}:p{j}"
            agents.append({"pane_id": pane, "workspace_id": ws, "agent": "claude"})
            registry.set(HerdrPaneMapping(room=room, handle=f"a{i}{j}", pane=pane, managed=True))

    def herdr_cli(args: list[str]) -> subprocess.CompletedProcess:
        if args[:2] == ["agent", "list"]:
            body = {"agents": [{**a, "agent_status": "idle"} for a in agents]}
        elif args[:2] == ["pane", "list"]:
            body = {"panes": [{"pane_id": a["pane_id"]} for a in agents]}
        else:
            body = {}
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": body}), "")

    return HerdrBridge(binary="/bin/sh", runner=herdr_cli, registry=registry), targets


def _passes(bridge: HerdrBridge, targets: list[tuple[str, str]], n: int) -> None:
    for _ in range(n):
        herdr.sync_pass(MyceliumConfig(), bridge, targets, room_filter=None, ttl_s=90.0, wait=False)


def test_a_pass_asks_each_room_twice_on_one_connection_and_each_agent_rarely(
    hub: Hub, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked: list[str] = []
    monkeypatch.setattr(
        herdr, "_manifest_on_hub", lambda _c, _room, handle: checked.append(handle) or True
    )
    bridge, targets = _bridge(tmp_path, rooms=3)

    _passes(bridge, targets, 4)

    # One client for every pass, so its connections stay open between them,
    # with its credential got again at the start of each pass after the first.
    assert hub.clients == 1
    assert hub.credentials == 3
    for i in range(3):
        assert hub.calls[f"POST room-{i} herdr-presence"] == 4
        assert hub.calls[f"GET room-{i} herdr-wakes"] == 4
    # Each agent's manifest is looked at on the first pass, not on every one.
    assert sorted(checked) == ["a00", "a01", "a10", "a11", "a20", "a21"]


def test_a_room_the_hub_doesnt_have_is_left_out_and_said_once(
    hub: Hub, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(herdr, "_manifest_on_hub", lambda *_a: True)
    hub.missing = ("room-1",)
    bridge, targets = _bridge(tmp_path, rooms=2)

    with caplog.at_level("WARNING", logger="mycelium.runner.sync"):
        _passes(bridge, targets, 3)

    asked = sum(n for call, n in hub.calls.items() if " room-1 " in call)
    assert asked == 1, "one 404, then the room is left out"
    assert hub.calls["GET room-0 herdr-wakes"] == 3
    said = [r for r in caplog.records if "has no room room-1" in r.getMessage()]
    assert len(said) == 1


def test_a_404_that_isnt_the_hub_saying_so_leaves_the_room_in(
    hub: Hub, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proxy answering 404 mid-redeploy is no reason to stop a room's wakes."""
    monkeypatch.setattr(herdr, "_manifest_on_hub", lambda *_a: True)
    hub.unrouted = ("room-1",)
    bridge, targets = _bridge(tmp_path, rooms=2)

    _passes(bridge, targets, 3)

    assert hub.calls["POST room-1 herdr-presence"] == 3
    assert hub.calls["GET room-1 herdr-wakes"] == 3
    assert herdr._unknown_rooms == {}
