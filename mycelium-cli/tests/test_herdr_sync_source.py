# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A machine's sync names itself to the hub, so machines sharing a room keep
their agents apart: its presence push and its wake drain both carry its id."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from mycelium.commands import herdr
from mycelium.config import MyceliumConfig
from tests.conftest import install_stand_in_hub


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        if request.method == "POST":
            calls.append((url, {"json": json.loads(request.content)}))
            return httpx.Response(204, request=request)
        calls.append((url, {"params": dict(request.url.params) or None}))
        return httpx.Response(200, json={"wakes": []}, request=request)

    install_stand_in_hub(monkeypatch).answer = answer
    herdr.sync_source.cache_clear()
    monkeypatch.setattr("mycelium.runner.daemon.runner_id", lambda: "laptop-ana-1a2b")
    yield calls
    herdr.sync_source.cache_clear()


def test_a_push_and_a_drain_both_name_this_machine(sent: list) -> None:
    config = MyceliumConfig()
    herdr._push_presence(config, "eng", {"scout": {"status": "idle", "title": None}}, 90.0)
    herdr.fetch_wakes(config, "eng")
    (push_url, push), (drain_url, drain) = sent
    assert push_url.endswith("/api/rooms/eng/sessions/herdr-presence")
    assert push["json"]["source"] == "laptop-ana-1a2b"
    assert drain_url.endswith("/api/rooms/eng/sessions/herdr-wakes")
    assert drain["params"] == {"source": "laptop-ana-1a2b"}


def test_with_no_id_the_hub_is_asked_as_before(sent: list, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise OSError("read-only home")

    herdr.sync_source.cache_clear()
    monkeypatch.setattr("mycelium.runner.daemon.runner_id", broken)
    config = MyceliumConfig()
    herdr._push_presence(config, "eng", {}, 90.0)
    herdr.fetch_wakes(config, "eng")
    (_u, push), (_v, drain) = sent
    assert "source" not in push["json"]
    assert drain["params"] is None


def test_a_wake_this_machine_cant_read_costs_only_that_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draining empties the hub's queue, so a wake shaped by a hub a version
    apart must not take the others with it."""
    wakes = [
        {"handle": "scout", "reason": "mention", "id": "w1", "seen_by": "newer hub"},
        {"reason": "mention", "id": "w2"},  # no handle: this machine can't read it
        {"handle": "lead", "reason": "turn", "id": "w3"},
    ]
    install_stand_in_hub(monkeypatch).answer = lambda _request: {"wakes": wakes}
    herdr.sync_source.cache_clear()
    monkeypatch.setattr("mycelium.runner.daemon.runner_id", lambda: "laptop-ana-1a2b")
    got = herdr.fetch_wakes(MyceliumConfig(), "eng")
    assert [w.handle for w in got] == ["scout", "lead"]
