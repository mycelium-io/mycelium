# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the ``mycelium board`` command group (issue #493)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from mycelium.commands import board as board_cmd
from tests.conftest import FakeHTTPX, FakeResp

runner = CliRunner()

_BOARD = {
    "room": "handshake",
    "members": ["agent-y", "julia"],
    "counts": {"needs": 2, "flight": 1, "resolved": 1},
    "items": [
        {
            "id": "d3f1c2ab-0000-0000-0000-000000000001",
            "source": "ledger",
            "kind": "decision",
            "state": "open",
            "title": "JWT TTL — 15m or 60m?",
            "choices": ["15m", "60m"],
            "owner": {"handle": "agent-y", "kind": "agent", "present": True},
            "provenance": "from agent-y",
            "age": "6m",
            "needs_you": True,
        },
        {
            "id": "a91b0000-0000-0000-0000-000000000002",
            "source": "ledger",
            "kind": "concern",
            "state": "blocked",
            "title": "Enable thin-spoke join",
            "waiting_on": "#502",
            "age": "40m",
            "needs_you": True,
        },
        {
            "id": "plan:tasks:3",
            "source": "plan",
            "kind": "action",
            "state": "in_progress",
            "title": "Cache TTL sweep",
            "needs_you": False,
        },
        {
            "id": "b90d0000-0000-0000-0000-000000000003",
            "source": "ledger",
            "kind": "action",
            "state": "resolved",
            "title": "Fix path traversal",
            "note": "PR #499 merged",
            "needs_you": False,
        },
    ],
}


@pytest.fixture(autouse=True)
def _stub_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve config + room without touching disk or env."""
    monkeypatch.setattr(
        board_cmd.MyceliumConfig,
        "load",
        classmethod(lambda _cls: SimpleNamespace(server=SimpleNamespace(api_url="http://bk:8000"))),
    )
    monkeypatch.setattr(board_cmd, "_resolve_room", lambda _cfg, room: room or "handshake")


def test_board_default_shows_needs_you(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board_cmd, "_fetch_board", lambda _u, _r: _BOARD)
    result = runner.invoke(board_cmd.app, [])
    assert result.exit_code == 0, result.output
    assert "NEEDS YOU" in result.output
    assert "JWT TTL" in result.output
    # Resolved rows are hidden unless --all.
    assert "Fix path traversal" not in result.output


def test_board_all_includes_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board_cmd, "_fetch_board", lambda _u, _r: _BOARD)
    result = runner.invoke(board_cmd.app, ["--all"])
    assert result.exit_code == 0, result.output
    assert "RESOLVED" in result.output
    assert "Fix path traversal" in result.output


def test_short_id_prefix_resolves() -> None:
    """A short prefix picks the one matching item; a full UUID also works."""
    item = board_cmd._resolve_item(_BOARD["items"], "d3f1c2ab")
    assert item["title"].startswith("JWT TTL")
    item2 = board_cmd._resolve_item(_BOARD["items"], "plan:tasks:3")
    assert item2["source"] == "plan"


def test_ambiguous_id_raises() -> None:
    items = [{"id": "abc111"}, {"id": "abc222"}]
    with pytest.raises(Exception, match="ambiguous"):
        board_cmd._resolve_item(items, "abc")


def test_resolve_verb_posts_to_endpoint(
    fake_httpx: FakeHTTPX, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(board_cmd, "_fetch_board", lambda _u, _r: _BOARD)
    fake_httpx.respond_with(lambda *_a: FakeResp(None, status_code=204))
    result = runner.invoke(board_cmd.app, ["resolve", "d3f1c2ab"])
    assert result.exit_code == 0, result.output
    method, url, _body = fake_httpx.calls[-1]
    assert method == "POST"
    assert url == "/api/rooms/handshake/board/items/d3f1c2ab-0000-0000-0000-000000000001/resolve"


def test_claim_passes_owner(fake_httpx: FakeHTTPX, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board_cmd, "_fetch_board", lambda _u, _r: _BOARD)
    fake_httpx.respond_with(lambda *_a: FakeResp(None, status_code=204))
    result = runner.invoke(board_cmd.app, ["claim", "d3f1c2ab", "--to", "agent-y"])
    assert result.exit_code == 0, result.output
    _method, _url, body = fake_httpx.calls[-1]
    assert body == {"owner": "agent-y"}


def test_capture_posts_text(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"id": "cap1", "title": "spokes might break"}))
    result = runner.invoke(board_cmd.app, ["capture", "spokes might break"])
    assert result.exit_code == 0, result.output
    method, url, body = fake_httpx.calls[-1]
    assert method == "POST"
    assert url == "/api/rooms/handshake/board/capture"
    assert body["text"] == "spokes might break"
