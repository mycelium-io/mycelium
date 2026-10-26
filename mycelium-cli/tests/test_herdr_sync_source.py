# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A machine's sync names itself to the hub, so machines sharing a room keep
their agents apart: its presence push and its wake drain both carry its id."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from mycelium.commands import herdr
from mycelium.config import MyceliumConfig


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def post(url: str, **kw: Any) -> httpx.Response:
        calls.append((url, kw))
        return httpx.Response(204, request=httpx.Request("POST", url))

    def get(url: str, **kw: Any) -> httpx.Response:
        calls.append((url, kw))
        return httpx.Response(200, json={"wakes": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
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
