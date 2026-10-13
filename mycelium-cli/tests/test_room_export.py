"""Tests for `mycelium room export`: a room's history written to local JSON lines.

A fake hub answers the three reads the export makes (the wire replay, the board's
memory listing, the roster) with the shapes the real routes return, so these
cover paging, the cursor, the flat record, redaction and the command's output.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium import room_export
from mycelium.commands import room as room_cmd

ROOM = "r1"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _frame(
    n: int,
    sender: str,
    *,
    ptype: str = "message",
    text: str | None = None,
    episode: str = "live",
    data: dict[str, Any] | None = None,
    role: str = "agent",
) -> dict[str, Any]:
    urn = f"urn:ioc:mycelium:episode:{ROOM}:{episode}"
    content: dict[str, Any] = {
        "l9": {
            "header": {
                "message": {"episode": urn, "id": f"m{n}", "parents": []},
                "participants": {"actors": [{"id": sender, "role": role}]},
            },
            "payload": {"type": ptype, "data": data or {}},
        }
    }
    if text is not None:
        content["content"] = text
    return {
        "id": f"m{n}",
        "sender_handle": sender,
        "message_type": "l9_exchange",
        "content": json.dumps(content),
        "created_at": (T0 + timedelta(minutes=n)).isoformat(),
        "room_name": ROOM,
        "episode": urn,
    }


class _Resp:
    def __init__(self, body: Any, status: int = 200) -> None:
        self._body = body
        self.status_code = status

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError(self.status_code)


class FakeHub:
    """Answers like the hub: the wire replay is oldest first, the last ``limit``
    frames strictly before ``before``."""

    def __init__(self, frames: list[dict[str, Any]], rows: list[dict[str, Any]] | None = None):
        self.frames = frames
        self.rows = rows or []
        self.wire_calls = 0

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> _Resp:
        params = params or {}
        path = url
        if path.endswith("/messages/wire"):
            self.wire_calls += 1
            frames = self.frames
            if params.get("before"):
                cut = datetime.fromisoformat(params["before"])
                frames = [f for f in frames if datetime.fromisoformat(f["created_at"]) < cut]
            return _Resp(frames[-params["limit"] :])
        if path.endswith("/memory"):
            prefix = params["prefix"]
            page = [r for r in self.rows if r["key"].startswith(prefix)]
            return _Resp(page[params["offset"] : params["offset"] + params["limit"]])
        if path.endswith("/agents"):
            return _Resp([{"handle": "coder"}, {"handle": "reviewer"}])
        if path == "/api/users":
            return _Resp({"users": [{"handle": "julia"}]})
        return _Resp({"detail": "Not Found"}, 404)


ROW = {
    "key": "work/fix-login",
    "content_text": "Fix login\n\nThe body.",
    "episode": f"urn:ioc:mycelium:episode:{ROOM}:abc123",
    "meta": {"status": "open", "assignee": "coder"},
    "created_by": "julia",
    "updated_by": "julia",
    "version": 1,
    "created_at": T0.isoformat(),
    "updated_at": T0.isoformat(),
}


def _read(out) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (out / "messages.jsonl").read_text().splitlines()]


def test_pages_back_through_the_whole_room_in_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(room_export, "WIRE_PAGE", 2)
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(5)])

    result = room_export.export_room(hub, ROOM, tmp_path)

    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3", "m4"]
    assert hub.wire_calls == 3
    assert (result.new, result.total, result.from_start) == (5, 5, True)


def test_a_record_is_flat_and_says_who_where_and_what(tmp_path) -> None:
    hub = FakeHub(
        [
            _frame(0, "julia", text="@coder fix it @~reviewer fyi @!coder now", role="human"),
            _frame(1, "coder", ptype="reply", text="done", episode="abc123"),
            _frame(
                2,
                "system",
                ptype="notice",
                role="coordinator",
                data={
                    "subkind": "resolved",
                    "title": "Fix login",
                    "by": "coder",
                    "episode": f"urn:ioc:mycelium:episode:{ROOM}:abc123",
                },
            ),
            _frame(3, "aligner", text="round one", role="coordinator"),
        ],
        rows=[ROW],
    )

    room_export.export_room(hub, ROOM, tmp_path)
    ask, reply, notice, engine = _read(tmp_path)

    assert ask["sender_kind"] == "person"
    assert ask["channel"] == "live"
    assert ask["mentions"] == [
        {"handle": "coder", "mode": "plain"},
        {"handle": "reviewer", "mode": "silent"},
        {"handle": "coder", "mode": "urgent"},
    ]
    assert reply["sender_kind"] == "agent"
    assert (reply["channel"], reply["thread"], reply["task"]) == (
        "thread",
        "abc123",
        "work/fix-login",
    )
    assert notice["notice"] == "resolved"
    assert notice["text"] == "[resolved] Fix login by @coder"
    assert notice["refers_to_task"] == "work/fix-login"
    assert notice["mentions"] == []
    assert engine["sender_kind"] == "engine"

    board = json.loads((tmp_path / "board.json").read_text())
    assert board[0]["title"] == "Fix login"
    assert board[0]["thread"] == "abc123"
    assert board[0]["meta"]["assignee"] == "coder"


def test_a_second_run_appends_only_what_is_new(tmp_path) -> None:
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(3)])
    room_export.export_room(hub, ROOM, tmp_path)

    hub.frames += [_frame(n, "coder", text=f"msg {n}") for n in range(3, 5)]
    result = room_export.export_room(hub, ROOM, tmp_path)

    assert (result.new, result.total, result.from_start) == (2, 5, False)
    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3", "m4"]

    again = room_export.export_room(hub, ROOM, tmp_path)
    assert (again.new, again.total) == (0, 5)


def test_a_cursor_whose_frame_is_gone_still_stops_where_it_did(tmp_path) -> None:
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(3)])
    room_export.export_room(hub, ROOM, tmp_path)

    hub.frames = [f for f in hub.frames if f["id"] != "m2"] + [_frame(3, "coder", text="new")]
    result = room_export.export_room(hub, ROOM, tmp_path)

    assert result.new == 1
    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3"]


def test_since_bounds_a_first_export(tmp_path) -> None:
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(5)])

    room_export.export_room(hub, ROOM, tmp_path, since=T0 + timedelta(minutes=3))

    assert [r["id"] for r in _read(tmp_path)] == ["m3", "m4"]


def test_redact_replaces_secrets_and_keeps_github(tmp_path) -> None:
    text = (
        "mail a@b.co, see https://example.com/x and https://github.com/o/r/pull/1, "
        "token ghp_abcdefghijklmnopqrstuvwxyz0123, password=hunter2hunter2, in /Users/someone/code"
    )
    hub = FakeHub([_frame(0, "coder", text=text)])

    room_export.export_room(hub, ROOM, tmp_path, redacted=True)
    (line,) = _read(tmp_path)

    assert line["text"] == (
        "mail <EMAIL>, see <URL> and https://github.com/o/r/pull/1, "
        "token <TOKEN>, password=<TOKEN>, in /Users/<USER>/code"
    )


def test_an_export_directory_belongs_to_one_room_and_one_mode(tmp_path) -> None:
    hub = FakeHub([_frame(0, "coder", text="hi")])
    room_export.export_room(hub, ROOM, tmp_path)

    with pytest.raises(room_export.ExportError, match="not 'other'"):
        room_export.export_room(hub, "other", tmp_path)
    with pytest.raises(room_export.ExportError, match="not redacted"):
        room_export.export_room(hub, ROOM, tmp_path, redacted=True)


def _patch_command(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    monkeypatch.setattr(room_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(room_cmd, "_resolve_room", lambda _c, r: r or ROOM)

    @contextmanager
    def fake_client(*_args: Any, **_kwargs: Any):
        yield hub

    monkeypatch.setattr(room_cmd, "hub_client", fake_client)


def test_the_command_says_what_it_wrote(tmp_path, monkeypatch) -> None:
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(2)], rows=[ROW])
    _patch_command(monkeypatch, hub)
    out = tmp_path / "export"

    first = CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(out)])
    assert first.exit_code == 0, first.output
    assert f"Exported 2 messages from {ROOM} (2 in the export) and 1 board rows" in first.output

    second = CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(out), "--json"])
    assert second.exit_code == 0, second.output
    assert json.loads(second.output) == {
        "room": ROOM,
        "out": str(out),
        "new": 0,
        "total": 2,
        "board_rows": 1,
        "from_start": False,
    }


def test_the_command_refuses_a_mismatched_directory(tmp_path, monkeypatch) -> None:
    hub = FakeHub([_frame(0, "coder", text="hi")])
    _patch_command(monkeypatch, hub)
    out = tmp_path / "export"
    CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(out)])

    result = CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(out), "--redact"])

    assert result.exit_code == 1
    assert "not redacted" in result.output
