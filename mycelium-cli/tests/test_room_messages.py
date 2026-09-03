"""Tests for `mycelium room messages` — the point-in-time message reader.

The command wraps the generated ``list_messages`` client call. These tests
patch that call (and the config/room/client plumbing) and assert on rendering,
filter pass-through, and the empty case.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from mycelium.commands import room as room_cmd


def _make_messages() -> list:
    from mycelium_backend_client.models import MessageRead

    stamp = datetime.datetime(2026, 6, 11, 21, 22, 56)  # noqa: DTZ001 — fixed for assertions
    return [
        MessageRead(
            id=uuid4(),
            sender_handle="operator",
            message_type="broadcast",
            content="@cc-x reply with OK",
            created_at=stamp,
        ),
        MessageRead(
            id=uuid4(),
            sender_handle="cc-x",
            message_type="direct",
            content="OK from cc-x",
            created_at=stamp,
        ),
    ]


def _patch_common(monkeypatch: pytest.MonkeyPatch, sync_fn) -> None:
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    monkeypatch.setattr(room_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(room_cmd, "_resolve_room", lambda _c, _r: "msgtest")

    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = Mock(name="client")
    fake_cm.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: fake_cm)
    # The wire call lives in the shared chat helper now; both surfaces use it.
    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: fake_cm)

    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync",
        sync_fn,
    )


def test_room_messages_renders_with_type_and_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MessageListResponse

    msgs = _make_messages()
    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return MessageListResponse(messages=msgs, total=len(msgs))

    _patch_common(monkeypatch, fake_sync)

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--limit", "5"])

    assert result.exit_code == 0, result.output
    assert "operator [broadcast]" in result.output
    assert "@cc-x reply with OK" in result.output
    assert "cc-x [direct]" in result.output
    assert "OK from cc-x" in result.output
    assert "2 messages" in result.output
    assert captured["limit"] == 5
    # The short id is what `room amend` takes, so reading a room hands you one.
    for m in msgs:
        assert str(m.id)[:8] in result.output


def test_room_messages_marks_an_amended_message_as_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium_backend_client.models import MessageListResponse

    stamp = datetime.datetime(2026, 6, 11, 21, 22, 56)  # noqa: DTZ001 — fixed for assertions
    revised = _make_messages()[:1]
    revised[0].edited_at = stamp
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=revised, total=1))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"])

    assert result.exit_code == 0, result.output
    assert "(edited)" in result.output


def test_room_messages_passes_sender_and_type_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MessageListResponse

    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return MessageListResponse(messages=[], total=0)

    _patch_common(monkeypatch, fake_sync)

    result = CliRunner().invoke(
        room_cmd.app,
        ["messages", "msgtest", "--sender", "cc-x", "--type", "direct"],
    )

    assert result.exit_code == 0, result.output
    assert captured["sender"] == "cc-x"
    assert captured["message_type"] == "direct"
    assert "no messages" in result.output


def test_room_messages_singular_count(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MessageListResponse

    one = _make_messages()[:1]
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=one, total=1))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"])

    assert result.exit_code == 0, result.output
    assert "1 message," in result.output  # singular, not "1 messages"


def test_room_messages_shows_full_content_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The read-the-transcript command renders full content, never clipped."""
    from mycelium_backend_client.models import MessageListResponse, MessageRead

    long_text = "x" * 300 + " END-MARKER"
    msg = MessageRead(
        id=uuid4(),
        sender_handle="operator",
        message_type="broadcast",
        content=long_text,
        created_at=datetime.datetime(2026, 6, 11, 21, 22, 56),  # noqa: DTZ001
    )
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=[msg], total=1))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"])

    assert result.exit_code == 0, result.output
    assert "END-MARKER" in result.output  # full content survives
    assert "…" not in result.output  # no truncation ellipsis


def test_room_messages_indents_multiline_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-line content stays readable — continuation lines indented, not
    flattened into a single space-joined line."""
    from mycelium_backend_client.models import MessageListResponse, MessageRead

    msg = MessageRead(
        id=uuid4(),
        sender_handle="operator",
        message_type="broadcast",
        content="first line\nsecond line",
        created_at=datetime.datetime(2026, 6, 11, 21, 22, 56),  # noqa: DTZ001
    )
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=[msg], total=1))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"])

    assert result.exit_code == 0, result.output
    assert "first line" in result.output
    assert "second line" in result.output


def test_room_messages_passes_the_cursors_through(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MessageListResponse

    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return MessageListResponse(messages=[], total=0)

    _patch_common(monkeypatch, fake_sync)

    result = CliRunner().invoke(
        room_cmd.app,
        [
            "messages",
            "msgtest",
            "--since",
            "2026-09-03T09:00:00Z",
            "--before",
            "2026-09-03T12:00:00+00:00",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["since"] == datetime.datetime(2026, 9, 3, 9, 0, tzinfo=datetime.UTC)
    assert captured["before"] == datetime.datetime(2026, 9, 3, 12, 0, tzinfo=datetime.UTC)


def test_room_messages_takes_an_age_as_a_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MessageListResponse

    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return MessageListResponse(messages=[], total=0)

    _patch_common(monkeypatch, fake_sync)

    started = datetime.datetime.now(datetime.UTC)
    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--before", "2h"])

    assert result.exit_code == 0, result.output
    before = captured["before"]
    assert before.tzinfo is not None
    # "2h" means two hours before the command ran, give or take the run itself.
    assert abs((started - before) - datetime.timedelta(hours=2)) < datetime.timedelta(seconds=5)


def test_room_messages_rejects_a_stamp_it_cannot_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MessageListResponse

    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=[], total=0))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--before", "yesterday"])

    assert result.exit_code != 0
    assert "neither an ISO 8601 stamp nor an age" in result.output


def test_room_messages_names_the_cursor_for_the_page_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium_backend_client.models import MessageListResponse

    msgs = _make_messages()
    # Newest first: the second line is the oldest shown, so its stamp is the cursor.
    msgs[1].created_at = datetime.datetime(2026, 6, 11, 21, 20, 0, tzinfo=datetime.UTC)
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=msgs, total=7))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert "5 older" in result.output
    assert (
        "mycelium room messages msgtest --limit 2 --before 2026-06-11T21:20:00+00:00"
        in result.output
    )


def test_room_messages_says_nothing_about_older_when_the_page_is_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium_backend_client.models import MessageListResponse

    msgs = _make_messages()
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=msgs, total=len(msgs)))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"])

    assert result.exit_code == 0, result.output
    assert "older" not in result.output
    assert "--before" not in result.output


def test_room_messages_json_carries_the_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from mycelium_backend_client.models import MessageListResponse

    msgs = _make_messages()
    msgs[1].created_at = datetime.datetime(2026, 6, 11, 21, 20, 0, tzinfo=datetime.UTC)
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=msgs, total=7))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"], obj={"json": True})

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 7
    assert payload["older_before"] == "2026-06-11T21:20:00+00:00"


def test_json_cursor_is_null_when_the_page_is_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from mycelium_backend_client.models import MessageListResponse

    msgs = _make_messages()
    _patch_common(monkeypatch, lambda **_kw: MessageListResponse(messages=msgs, total=len(msgs)))

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"], obj={"json": True})

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["older_before"] is None


def test_parse_stamp_reads_iso_and_ages() -> None:
    from mycelium import chat

    now = datetime.datetime(2026, 9, 3, 12, 0, tzinfo=datetime.UTC)
    assert chat.parse_stamp("2026-09-03T09:00:00Z") == now.replace(hour=9)
    # A naive stamp is what the hub writes; it is read back as UTC, not local time.
    assert chat.parse_stamp("2026-09-03T09:00:00") == now.replace(hour=9)
    assert chat.parse_stamp("30m", now=now) == now - datetime.timedelta(minutes=30)
    assert chat.parse_stamp("2h", now=now) == now - datetime.timedelta(hours=2)
    assert chat.parse_stamp("1d", now=now) == now - datetime.timedelta(days=1)
    assert chat.parse_stamp(" 15 s ", now=now) == now - datetime.timedelta(seconds=15)
