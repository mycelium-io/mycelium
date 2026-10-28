"""Tests for `mycelium room export`: a room's history written to local JSON lines.

A fake hub answers the three reads the export makes (the wire replay, the board's
memory listing, the roster) with the shapes the real routes return, so these
cover paging, the cursor, the flat record, redaction and the command's output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import room_export
from mycelium.commands import room as room_cmd
from mycelium.config import MyceliumConfig
from mycelium_backend_client import Client
from tests.conftest import install_stand_in_hub, memory_read

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


class FakeHub(httpx.Client):
    """Answers like the hub: the wire replay is oldest first, the last ``limit``
    frames strictly before ``before``.

    An ``httpx.Client`` like the one ``hub_client`` gives the command, answering
    at its transport, so the export's typed calls parse what it says. A command
    test hands :meth:`answer` to the stand-in hub instead (``_patch_command``).
    """

    def __init__(self, frames: list[dict[str, Any]], rows: list[dict[str, Any]] | None = None):
        super().__init__(
            base_url="http://localhost:8000", transport=httpx.MockTransport(self._send)
        )
        self.frames = frames
        self.rows = rows or []
        self.wire_calls = 0

    def _send(self, request: httpx.Request) -> httpx.Response:
        answered = self.answer(request)
        status, payload = answered if isinstance(answered, tuple) else (200, answered)
        return httpx.Response(status, json=payload, request=request)

    def answer(self, request: httpx.Request) -> Any:
        params = request.url.params
        path = request.url.path
        if path.endswith("/messages/wire"):
            self.wire_calls += 1
            frames = self.frames
            if params.get("before"):
                cut = datetime.fromisoformat(params["before"])
                frames = [f for f in frames if datetime.fromisoformat(f["created_at"]) < cut]
            return frames[-int(params["limit"]) :]
        if path.endswith("/memory"):
            prefix, offset, limit = params["prefix"], int(params["offset"]), int(params["limit"])
            page = [r for r in self.rows if r["key"].startswith(prefix)]
            return page[offset : offset + limit]
        if path.endswith("/agents"):
            return [
                {"handle": "coder", "adapter": "claude-code"},
                {"handle": "reviewer", "adapter": "claude-code"},
            ]
        if path == "/api/users":
            return {"users": [{"handle": "julia"}], "total": 1}
        return 404, {"detail": "Not Found"}


ROW = memory_read(
    "work/fix-login",
    ROOM,
    content_text="Fix login\n\nThe body.",
    episode=f"urn:ioc:mycelium:episode:{ROOM}:abc123",
    meta={"status": "open", "assignee": "coder"},
    created_by="julia",
    updated_by="julia",
    version=1,
    created_at=T0.isoformat(),
    updated_at=T0.isoformat(),
)


def _typed(hub: FakeHub) -> Client:
    """The typed client the command hands the export, over ``hub``."""
    client = Client(base_url=str(hub.base_url), raise_on_unexpected_status=False)
    return client.set_httpx_client(hub)


def _read(out) -> list[dict[str, Any]]:
    text = (out / "messages.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_pages_back_through_the_whole_room_in_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(room_export, "WIRE_PAGE", 2)
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(5)])

    result = room_export.export_room(_typed(hub), ROOM, tmp_path)

    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3", "m4"]
    assert hub.wire_calls > 1
    assert (result.new, result.total, result.from_start) == (5, 5, True)


def test_stamps_are_written_as_the_hub_sent_them(tmp_path) -> None:
    frame = _frame(0, "coder", text="hi")
    frame["created_at"] = "2026-10-01T12:00:00Z"
    row = {**ROW, "created_at": "2026-10-01T12:00:00Z"}

    room_export.export_room(_typed(FakeHub([frame], rows=[row])), ROOM, tmp_path)

    assert '"at": "2026-10-01T12:00:00Z"' in (tmp_path / "messages.jsonl").read_text()
    assert '"created_at": "2026-10-01T12:00:00Z"' in (tmp_path / "board.json").read_text()


def test_frames_sharing_a_stamp_across_a_page_boundary_are_all_kept(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(room_export, "WIRE_PAGE", 2)
    frames = [_frame(n, "coder", text=f"msg {n}") for n in range(4)]
    frames[1]["created_at"] = frames[2]["created_at"]  # m1 and m2 share a stamp
    hub = FakeHub(frames)

    room_export.export_room(_typed(hub), ROOM, tmp_path)

    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3"]


def test_files_are_utf8_whatever_the_platform(tmp_path) -> None:
    hub = FakeHub([_frame(0, "coder", text="ship it 🚀, Zoë, 東京")], rows=[ROW])

    room_export.export_room(_typed(hub), ROOM, tmp_path)

    raw = (tmp_path / "messages.jsonl").read_bytes()
    assert "ship it 🚀, Zoë, 東京".encode() in raw


def test_the_default_folder_is_outside_the_working_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert room_export.default_out(ROOM) == tmp_path / "mycelium-exports" / ROOM

    checkout = tmp_path / "repo"
    (checkout / ".git").mkdir(parents=True)
    assert room_export.in_git_work_tree(checkout / "exports" / ROOM)
    assert not room_export.in_git_work_tree(tmp_path / "elsewhere")


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

    room_export.export_room(_typed(hub), ROOM, tmp_path)
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
    room_export.export_room(_typed(hub), ROOM, tmp_path)

    hub.frames += [_frame(n, "coder", text=f"msg {n}") for n in range(3, 5)]
    result = room_export.export_room(_typed(hub), ROOM, tmp_path)

    assert (result.new, result.total, result.from_start) == (2, 5, False)
    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3", "m4"]

    again = room_export.export_room(_typed(hub), ROOM, tmp_path)
    assert (again.new, again.total) == (0, 5)


def test_a_cursor_whose_frame_is_gone_still_stops_where_it_did(tmp_path) -> None:
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(3)])
    room_export.export_room(_typed(hub), ROOM, tmp_path)

    hub.frames = [f for f in hub.frames if f["id"] != "m2"] + [_frame(3, "coder", text="new")]
    result = room_export.export_room(_typed(hub), ROOM, tmp_path)

    assert result.new == 1
    assert [r["id"] for r in _read(tmp_path)] == ["m0", "m1", "m2", "m3"]


def test_since_bounds_a_first_export(tmp_path) -> None:
    hub = FakeHub([_frame(n, "coder", text=f"msg {n}") for n in range(5)])

    room_export.export_room(_typed(hub), ROOM, tmp_path, since=T0 + timedelta(minutes=3))

    assert [r["id"] for r in _read(tmp_path)] == ["m3", "m4"]


def test_redact_replaces_secrets_and_keeps_github(tmp_path) -> None:
    text = (
        "mail a@b.co, see https://example.com/x and https://github.com/o/r/pull/1, "
        "token ghp_abcdefghijklmnopqrstuvwxyz0123, password=hunter2hunter2, in /Users/someone/code"
    )
    hub = FakeHub([_frame(0, "coder", text=text)])

    room_export.export_room(_typed(hub), ROOM, tmp_path, redacted=True)
    (line,) = _read(tmp_path)

    assert line["text"] == (
        "mail <EMAIL>, see <URL> and https://github.com/o/r/pull/1, "
        "token <TOKEN>, password=<TOKEN>, in /Users/<USER>/code"
    )


def test_an_export_directory_belongs_to_one_room_and_one_mode(tmp_path) -> None:
    hub = FakeHub([_frame(0, "coder", text="hi")])
    room_export.export_room(_typed(hub), ROOM, tmp_path)

    with pytest.raises(room_export.ExportError, match="not 'other'"):
        room_export.export_room(_typed(hub), "other", tmp_path)
    with pytest.raises(room_export.ExportError, match="not redacted"):
        room_export.export_room(_typed(hub), ROOM, tmp_path, redacted=True)


def _patch_command(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    fake_config = MyceliumConfig()
    fake_config.server.api_url = "http://localhost:8000"
    monkeypatch.setattr(MyceliumConfig, "load", classmethod(lambda _cls, *_a, **_k: fake_config))
    monkeypatch.setattr(room_cmd, "_resolve_room", lambda _c, r: r or ROOM)
    monkeypatch.setattr("mycelium.caller.find_membership", lambda *_a, **_k: None)
    install_stand_in_hub(monkeypatch).answer = hub.answer


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


def test_the_command_warns_about_a_folder_in_a_git_checkout(tmp_path, monkeypatch) -> None:
    hub = FakeHub([_frame(0, "coder", text="hi")])
    _patch_command(monkeypatch, hub)
    (tmp_path / ".git").mkdir()

    result = CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(tmp_path / "x")])

    assert result.exit_code == 0, result.output
    assert "inside a git checkout" in result.output


def test_the_command_refuses_a_mismatched_directory(tmp_path, monkeypatch) -> None:
    hub = FakeHub([_frame(0, "coder", text="hi")])
    _patch_command(monkeypatch, hub)
    out = tmp_path / "export"
    CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(out)])

    result = CliRunner().invoke(room_cmd.app, ["export", ROOM, "--out", str(out), "--redact"])

    assert result.exit_code == 1
    assert "not redacted" in result.output
