# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Demo's and metrics' hub calls carry the caller's credential.

On a hub with sign-in on, a call that sends none is refused with a 401, and
the commands below used to read that as "no rooms" or "not reachable". Each
goes through the typed client now, which attaches the credential for the hub
that issued it.
"""

from __future__ import annotations

import httpx
import pytest

from mycelium import client
from mycelium.commands import demo
from mycelium.commands import metrics as metrics_cmd
from mycelium.config import MyceliumConfig

_HUB = "https://hub.example.com"


class _Hub:
    """Answers every request like a gated hub would, and keeps what was sent."""

    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if request.headers.get("Authorization") != "Bearer t":
            return httpx.Response(401, json={"detail": "Not authenticated"}, request=request)
        if request.url.path == "/api/rooms":
            room = {"id": 1, "name": "lobby", "mas_id": "m1", "is_public": True, "created_at": _AT}
            return httpx.Response(200, json=[room], request=request)
        messages = [_message("Growth"), _message("risk")]
        return httpx.Response(200, json={"messages": messages, "total": 2}, request=request)


_AT = "2026-08-24T10:00:00+00:00"


def _message(sender: str) -> dict:
    """A message as the hub's ``MessageRead`` answers it."""
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "sender_handle": sender,
        "message_type": "message",
        "content": "hi",
        "created_at": _AT,
    }


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> _Hub:
    fake = _Hub()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake.handle)
    monkeypatch.setattr(client, "auth_headers", lambda *_a, **_k: {"Authorization": "Bearer t"})
    monkeypatch.setattr("mycelium.caller.find_membership", lambda *_a, **_k: None)
    return fake


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> MyceliumConfig:
    cfg = MyceliumConfig()
    cfg.server.api_url = _HUB
    cfg.llm.model = "anthropic/claude-sonnet-4-6"
    monkeypatch.setattr(MyceliumConfig, "load", classmethod(lambda _cls, *_a, **_k: cfg))
    return cfg


def test_demo_prereqs_find_a_gated_hub_reachable(hub: _Hub, config: MyceliumConfig) -> None:
    _, problems = demo._check_prereqs()
    assert [r.url.path for r in hub.sent] == ["/api/rooms"]
    assert not any("not reachable" in p for p in problems), problems


def test_demo_prereqs_say_a_refusal_is_a_sign_in_not_a_dead_hub(
    hub: _Hub, config: MyceliumConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client, "auth_headers", lambda *_a, **_k: {})
    _, problems = demo._check_prereqs()
    assert problems == [f"The hub at {_HUB} refused this computer. Try: mycelium login"]


def test_demo_reads_who_posted_on_a_gated_hub(hub: _Hub, config: MyceliumConfig) -> None:
    assert demo._room_senders(config, "demo-room") == {"growth", "risk"}
    assert hub.sent[0].url.path == "/api/rooms/demo-room/messages"


def test_metrics_names_rooms_on_a_gated_hub(
    hub: _Hub, config: MyceliumConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(metrics_cmd, "_ROOM_LOOKUP_CACHE", None)
    monkeypatch.setattr(metrics_cmd, "_SNAPSHOT_BACKEND_FOR_LOOKUP", None)
    mas_to_name, name_to_mas = metrics_cmd._resolve_room_lookup()
    assert mas_to_name == {"m1": "lobby"}
    assert name_to_mas == {"lobby": "m1"}
    assert hub.sent[0].headers["Accept"] == "application/json"
