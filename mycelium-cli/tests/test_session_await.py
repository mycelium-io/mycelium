# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Regression tests for `mycelium session await`'s missed-tick pre-check.

Issue #405: the pre-check scanned every session under the room and returned on
the first `coordination_consensus` it found (unscoped), so an older completed
session's consensus permanently shadowed the current session's live ticks. The
scan must be scoped to the handle's session — the newest one in the room.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from typer.testing import CliRunner

from mycelium.commands import session as session_cmd


class _Resp:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        pass


class _EmptyStream:
    def __enter__(self) -> _EmptyStream:
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def iter_lines(self):
        return iter(())  # no live events → await falls through and returns


class _FakeClient:
    """Fake httpx.Client that records requested URLs and serves canned data."""

    def __init__(self, requested: list[str], sessions: list[dict], messages: dict) -> None:
        self._requested = requested
        self._sessions = sessions
        self._messages = messages

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def get(self, url: str, params=None):
        self._requested.append(url)
        if url.endswith("/coordination-sessions"):
            # Honor the newest-first + limit contract the endpoint provides.
            limit = (params or {}).get("limit", 200)
            return _Resp(200, self._sessions[:limit])
        room = url.split("/api/rooms/", 1)[1].rsplit("/messages", 1)[0]
        return _Resp(200, {"messages": self._messages.get(room, [])})

    def stream(self, _method: str, url: str, **_kw):
        self._requested.append(url)
        return _EmptyStream()


def _patch(monkeypatch, requested, sessions, messages):
    cfg = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    monkeypatch.setattr(session_cmd.MyceliumConfig, "load", classmethod(lambda _c: cfg))
    monkeypatch.setattr(session_cmd, "_resolve_room", lambda _c, _r: "R")
    monkeypatch.setattr(
        httpx, "Client", lambda *_a, **_k: _FakeClient(requested, sessions, messages)
    )


def _tick_msg(room: str, participant: str) -> dict:
    return {
        "message_type": "coordination_tick",
        "room_name": room,
        "content": json.dumps(
            {"kind": "negotiate", "payload": {"action": "respond", "participant_id": participant}}
        ),
    }


def _consensus_msg() -> dict:
    return {
        "message_type": "coordination_consensus",
        "room_name": "R:session:old",
        "content": json.dumps({"plan": "stale plan from a previous negotiation", "broken": False}),
    }


def test_await_ignores_stale_consensus_from_older_session(monkeypatch):
    """The bug (#405): newest session is live but its latest tick is for another
    agent, and an older session has a consensus. The pre-check must NOT return
    that stale consensus, and must never even scan the old session."""
    requested: list[str] = []
    sessions = [
        {"display_name": "R:session:new", "state": "negotiating"},  # newest first
        {"display_name": "R:session:old", "state": "complete"},
    ]
    messages = {
        "R:session:new": [_tick_msg("R:session:new", "other-agent")],  # not our handle
        "R:session:old": [_consensus_msg()],
    }
    _patch(monkeypatch, requested, sessions, messages)

    result = CliRunner().invoke(
        session_cmd.app, ["await", "-H", "julia-agent", "-r", "R", "-t", "1"]
    )

    # No stale consensus replayed (falls through to the live SSE stream instead).
    assert "stale plan" not in result.output
    # The old, completed session must never have been scanned.
    assert not any("R:session:old" in u for u in requested)


def test_await_returns_live_tick_for_this_handle(monkeypatch):
    """A missed tick addressed to this handle in the current session is replayed."""
    requested: list[str] = []
    sessions = [{"display_name": "R:session:new", "state": "negotiating"}]
    messages = {"R:session:new": [_tick_msg("R:session:new", "julia-agent")]}
    _patch(monkeypatch, requested, sessions, messages)

    result = CliRunner().invoke(
        session_cmd.app, ["await", "-H", "julia-agent", "-r", "R", "-t", "1"]
    )

    assert result.exit_code == 0, result.output
    out = json.loads(result.output.strip().splitlines()[-1])
    assert out.get("replayed") is True
    assert out.get("action") == "respond"


def test_await_falls_back_to_room_when_no_sessions(monkeypatch):
    """Inline / non-CFN mode (no session rows) still scans the room itself."""
    requested: list[str] = []
    messages = {"R": [_tick_msg("R", "julia-agent")]}
    _patch(monkeypatch, requested, [], messages)

    result = CliRunner().invoke(
        session_cmd.app, ["await", "-H", "julia-agent", "-r", "R", "-t", "1"]
    )

    assert result.exit_code == 0, result.output
    assert any(u.endswith("/api/rooms/R/messages") for u in requested)
