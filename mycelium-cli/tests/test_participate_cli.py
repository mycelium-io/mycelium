# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium await`` / ``mycelium respond`` — the server-held participant path.

Node-free: a stand-in hub answers at httpx's transport, so these exercise the
CLI plumbing — room resolution, the long-poll request/parse for ``await``, the
reply POST for ``respond``, and the ``--json`` agent contract. Membership +
marker parsing now live server-side, so the CLI is a thin HTTP client.

Both commands go through the generated typed client, which parses each answer
against ``openapi.json``, so every answer here is the shape the hub really
sends. The stand-in records each request, path relative to the hub's base URL.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from tests.conftest import install_stand_in_hub

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")


def _renewed(handle: str, *keys: str) -> dict:
    """The hub's ``AssignmentsRenewed``: the rows ``handle`` still holds."""
    return {
        "room": "demo",
        "handle": handle,
        "renewed": [{"key": k, "assignment": "held", "waiting_on": []} for k in keys],
    }


def _lease(key: str, assignment: str, since: str, **fields: object) -> dict:
    """A lease's state as the hub's ``AssignmentWatchRead`` answers it."""
    return {
        "key": key,
        "assignment": assignment,
        "waiting_on": [],
        "since": since,
        "changed": False,
        **fields,
    }


def test_await_prints_addressed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: {
        "room": "demo",
        "handle": "me",
        "prompt": "@me what is your position?",
        "sender": "mediator",
        "episode": "urn:ioc:mycelium:episode:demo:live",
        "topic": "urn:concept:mycelium:demo",
        "message_id": "tick-1",
    }

    result = runner.invoke(app, ["await", "--handle", "me", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["message_id"] == "tick-1"
    assert payload["prompt"] == "@me what is your position?"
    assert payload["sender"] == "mediator"

    request = hub.requests[0]
    assert (request.method, request.url.path) == ("GET", "/api/rooms/demo/await")
    assert request.url.params["handle"] == "me"


def test_await_timeout_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stand_in_hub(monkeypatch).answer = lambda _r: {
        "room": "demo",
        "handle": "me",
        "message": None,
    }

    result = runner.invoke(app, ["await", "--handle", "me", "--timeout", "1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["message"] is None


def test_resident_loop_stops_when_the_hub_refuses_the_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 ends the loop; a transient failure before it does not.

    Under a gated hub, awaiting a handle the token may not act as is a standing
    refusal — re-polling it forever would be a self-inflicted request flood.
    """
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    errors = iter(
        [
            (503, {"detail": "JWKS unavailable"}),
            (403, {"detail": "handle 'bot' is not the authenticated principal '@carol'"}),
        ]
    )

    def answer(request: httpx.Request) -> object:
        if request.url.path.endswith("/assignments/renew"):
            return _renewed("bot")
        return next(errors)

    hub = install_stand_in_hub(monkeypatch)
    hub.answer = answer

    result = runner.invoke(app, ["await", "--handle", "bot", "--loop", "--json"])
    assert result.exit_code == 1
    # Two polls: the blip was retried, the refusal was not.
    assert len(hub.sent("GET", "/api/rooms/demo/await")) == 2


def test_respond_posts_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: {"room": "demo", "handle": "me", "message_id": "r-1"}

    result = runner.invoke(
        app,
        ["respond", "I can move to 30%. [[mycelium: stance=accept]]", "--handle", "me", "--json"],
    )
    assert result.exit_code == 0

    request = hub.requests[0]
    assert (request.method, request.url.path) == ("POST", "/api/rooms/demo/reply")
    # The CLI sends raw text + handle; the backend parses the marker + records it.
    assert json.loads(request.content) == {
        "handle": "me",
        "text": "I can move to 30%. [[mycelium: stance=accept]]",
    }
    assert json.loads(result.stdout)["message_id"] == "r-1"


# ── awaiting a lease rather than the channel ─────────────────────────────────


def test_await_lease_orients_before_it_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh session's first read comes straight back with the row's state: an
    agent doesn't need a push, it needs the row current the next time it exists."""
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: _lease(
        "work/auth-spike",
        "held",
        "held|growth|2026-08-23T12:00:00+00:00|4",
        owner="growth",
        assignment_note=None,
    )

    result = runner.invoke(app, ["await", "--lease", "work/auth-spike", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["assignment"] == "held"

    request = hub.requests[0]
    assert (request.method, request.url.path) == ("GET", "/api/rooms/demo/assignments/await")
    assert request.url.params["key"] == "work/auth-spike"
    # No `since` on the first call — that is what makes it orientation.
    assert "since" not in request.url.params


def test_await_lease_passes_the_token_back_so_the_next_call_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orientation, then a wait: the token from one read is what the next one
    blocks against, so a loop sees each transition exactly once."""
    replies = [
        _lease("work/auth", "unclaimed", "t0", owner=None),
        _lease("work/auth", "held", "t1", owner="growth", changed=True),
    ]

    def answer(_request: httpx.Request) -> dict:
        if not replies:
            raise KeyboardInterrupt
        return replies.pop(0)

    hub = install_stand_in_hub(monkeypatch)
    hub.answer = answer
    runner.invoke(app, ["await", "--lease", "work/auth", "--loop", "--json"])

    assert hub.requests[0].url.params.get("since") is None
    assert hub.requests[1].url.params["since"] == "t0"


def test_await_lease_needs_no_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Watching a row is not participating as anyone: the lease is the subject."""
    install_stand_in_hub(monkeypatch).answer = lambda _r: _lease("work/x", "unclaimed", "t")
    assert runner.invoke(app, ["await", "--lease", "work/x", "--json"]).exit_code == 0


def test_await_with_nobody_to_wait_as_says_how_to_name_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no --as and nothing that resolves a handle, a turn has no recipient,
    so await refuses rather than waiting as a placeholder."""
    monkeypatch.setattr("mycelium.identity.resolve_actor", lambda *_a, **_k: "")
    result = runner.invoke(app, ["await"])
    assert result.exit_code == 2
    assert "--as" in result.output


def test_respond_with_nobody_to_send_as_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reply must name a real sender: no `cli-user` placeholder."""
    monkeypatch.setattr("mycelium.identity.resolve_actor", lambda *_a, **_k: "")
    result = runner.invoke(app, ["respond", "hello"])
    assert result.exit_code == 2
    assert "--as" in result.output


def test_respond_resolves_its_sender_without_a_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """--as is no longer required: the environment names the sender."""
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "env-agent")
    reply = {"room": "demo", "handle": "env-agent", "message_id": "m1"}
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: reply
    result = runner.invoke(app, ["respond", "hello", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == reply
    assert json.loads(hub.requests[-1].content)["handle"] == "env-agent"


def test_a_resident_loop_renews_the_claims_it_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Residency and assignment are kept alive by the same loop, so an agent that
    stops looping stops holding — with nobody writing that down."""

    def answer(request: httpx.Request) -> dict:
        if request.url.path.endswith("/assignments/renew"):
            return _renewed("growth", "work/auth-spike")
        raise KeyboardInterrupt

    hub = install_stand_in_hub(monkeypatch)
    hub.answer = answer
    runner.invoke(app, ["await", "--handle", "growth", "--loop"])

    seen = [(r.method, r.url.path) for r in hub.requests]
    assert ("POST", "/api/rooms/demo/assignments/renew") in seen
    # The renewal happens before the wait, so a claim never lapses while its
    # holder is sitting in a long poll.
    assert seen[0] == ("POST", "/api/rooms/demo/assignments/renew")


def test_a_renew_blip_does_not_drop_residency(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(request: httpx.Request) -> dict:
        if request.url.path.endswith("/assignments/renew"):
            raise httpx.ConnectError("hub hiccup", request=request)
        raise KeyboardInterrupt

    install_stand_in_hub(monkeypatch).answer = answer
    result = runner.invoke(app, ["await", "--handle", "growth", "--loop"])
    assert "renew error" in result.stdout
