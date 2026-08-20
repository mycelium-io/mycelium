# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium await`` / ``mycelium respond`` — the server-held participant path.

Node-free: ``httpx`` is stubbed so these exercise the CLI plumbing — room
resolution, the long-poll request/parse for ``await``, the reply POST for
``respond``, and the ``--json`` agent contract. Membership + marker parsing now
live server-side, so the CLI is a thin HTTP client.

Both commands build their client through ``mycelium.client.hub_client``, so the
requests here carry the session bearer when one is cached; the fake records the
request path relative to the hub's base URL.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from tests.conftest import FakeHTTPX, FakeResp

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")


def test_await_prints_addressed_message(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
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
    )

    result = runner.invoke(app, ["await", "--handle", "me", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["message_id"] == "tick-1"
    assert payload["prompt"] == "@me what is your position?"
    assert payload["sender"] == "mediator"

    method, path, params = fake_httpx.calls[0]
    assert (method, path) == ("GET", "/api/rooms/demo/await")
    assert params["handle"] == "me"


def test_await_timeout_exits_nonzero(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"room": "demo", "handle": "me", "message": None}))

    result = runner.invoke(app, ["await", "--handle", "me", "--timeout", "1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["message"] is None


def _http_error(status: int, detail: str) -> httpx.HTTPStatusError:
    """The error ``raise_for_status`` raises for a hub that refused the call."""
    request = httpx.Request("GET", "http://hub/api/rooms/demo/await")
    return httpx.HTTPStatusError(
        f"HTTP {status}",
        request=request,
        response=httpx.Response(status, json={"detail": detail}, request=request),
    )


def test_resident_loop_stops_when_the_hub_refuses_the_handle(
    fake_httpx: FakeHTTPX, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 403 ends the loop; a transient failure before it does not.

    Under a gated hub, awaiting a handle the token may not act as is a standing
    refusal — re-polling it forever would be a self-inflicted request flood.
    """
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    errors = iter(
        [
            _http_error(503, "JWKS unavailable"),
            _http_error(403, "handle 'bot' is not the authenticated principal '@carol'"),
        ]
    )

    def _refuse(*_a: object) -> FakeResp:
        raise next(errors)

    fake_httpx.respond_with(_refuse)

    result = runner.invoke(app, ["await", "--handle", "bot", "--loop", "--json"])
    assert result.exit_code == 1
    # Two polls: the blip was retried, the refusal was not.
    assert len(fake_httpx.calls) == 2


def test_respond_posts_reply(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp({"room": "demo", "handle": "me", "message_id": "r-1"})
    )

    result = runner.invoke(
        app,
        ["respond", "I can move to 30%. [[mycelium: stance=accept]]", "--handle", "me", "--json"],
    )
    assert result.exit_code == 0

    method, path, body = fake_httpx.calls[0]
    assert (method, path) == ("POST", "/api/rooms/demo/reply")
    # The CLI sends raw text + handle; the backend parses the marker + records it.
    assert body == {
        "handle": "me",
        "text": "I can move to 30%. [[mycelium: stance=accept]]",
    }
    assert json.loads(result.stdout)["message_id"] == "r-1"
