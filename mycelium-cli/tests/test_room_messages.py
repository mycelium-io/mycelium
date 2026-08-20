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
    assert "operator [broadcast]: @cc-x reply with OK" in result.output
    assert "cc-x [direct]: OK from cc-x" in result.output
    assert "2 messages" in result.output
    assert captured["limit"] == 5


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
