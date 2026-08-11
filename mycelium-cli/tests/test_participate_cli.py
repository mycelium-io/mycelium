# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium await`` / ``mycelium respond`` — the server-held participant path.

Node-free: ``httpx`` is stubbed so these exercise the CLI plumbing — room
resolution, the long-poll request/parse for ``await``, the reply POST for
``respond``, and the ``--json`` agent contract. Membership + marker parsing now
live server-side, so the CLI is a thin HTTP client.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import participate

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")


class _FakeResp:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


def test_await_prints_addressed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict | None = None, timeout: float | None = None) -> _FakeResp:
        assert url.endswith("/api/rooms/demo/await")
        assert params is not None and params["handle"] == "me"
        return _FakeResp(
            {
                "room": "demo",
                "handle": "me",
                "prompt": "@me what is your position?",
                "sender": "mediator",
                "episode": "urn:ioc:mycelium:episode:demo:live",
                "topic": "urn:concept:mycelium:demo",
                "message_id": "tick-1",
            }
        )

    monkeypatch.setattr(participate.httpx, "get", fake_get)

    result = runner.invoke(app, ["await", "--handle", "me", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["message_id"] == "tick-1"
    assert payload["prompt"] == "@me what is your position?"
    assert payload["sender"] == "mediator"


def test_await_timeout_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url, params=None, timeout=None):
        return _FakeResp({"room": "demo", "handle": "me", "message": None})

    monkeypatch.setattr(participate.httpx, "get", fake_get)
    result = runner.invoke(app, ["await", "--handle", "me", "--timeout", "1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["message"] is None


def test_respond_posts_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return _FakeResp({"room": "demo", "handle": "me", "message_id": "r-1"})

    monkeypatch.setattr(participate.httpx, "post", fake_post)

    result = runner.invoke(
        app,
        ["respond", "I can move to 30%. [[mycelium: stance=accept]]", "--handle", "me", "--json"],
    )
    assert result.exit_code == 0
    assert captured["url"].endswith("/api/rooms/demo/reply")
    # The CLI sends raw text + handle; the backend parses the marker + records it.
    assert captured["body"] == {
        "handle": "me",
        "text": "I can move to 30%. [[mycelium: stance=accept]]",
    }
    assert json.loads(result.stdout)["message_id"] == "r-1"
