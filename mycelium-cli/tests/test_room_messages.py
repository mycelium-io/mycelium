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

# What the generated client sends when a query parameter is simply not set.
UNSET_SENTINEL = __import__("mycelium_backend_client.types", fromlist=["UNSET"]).UNSET


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
    """The read-the-transcript command must not clip content (regression: was cut
    to 100 chars with an ellipsis, so long messages were unreadable)."""
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


def _page(contents: list[str], *, cursor: str | None):
    """One page of the room's history, with the cursor that continues past it."""
    from mycelium_backend_client.models import MessageListResponse, MessageRead

    return MessageListResponse(
        messages=[
            MessageRead(
                id=uuid4(),
                sender_handle="operator",
                message_type="broadcast",
                content=text,
                created_at=datetime.datetime(2026, 6, 11, 21, 22, 56),  # noqa: DTZ001
            )
            for text in contents
        ],
        total=6,
        next_cursor=cursor,
        has_more=cursor is not None,
    )


def _paged(monkeypatch: pytest.MonkeyPatch, pages: list) -> list[dict]:
    """Serve ``pages`` in order; returns the kwargs each call was made with."""
    calls: list[dict] = []
    queued = list(pages)

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return queued.pop(0) if queued else _page([], cursor=None)

    _patch_common(monkeypatch, fake_sync)
    return calls


def test_room_messages_walks_the_whole_history_with_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gap this closes: a room deeper than one page was unreadable past it."""
    calls = _paged(
        monkeypatch,
        [
            _page(["newest", "second"], cursor="c1"),
            _page(["third", "fourth"], cursor="c2"),
            _page(["fifth", "oldest"], cursor=None),
        ],
    )

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--limit", "2", "--all"])

    assert result.exit_code == 0, result.output
    for text in ("newest", "second", "third", "fourth", "fifth", "oldest"):
        assert text in result.output
    assert [c["cursor"] for c in calls] == [UNSET_SENTINEL, "c1", "c2"]
    assert "6 messages" in result.output


def test_room_messages_points_at_the_history_it_did_not_show(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page that isn't the end says so, and hands over the cursor to continue."""
    _paged(monkeypatch, [_page(["newest", "second"], cursor="c1")])

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert "more history" in result.output
    assert "--cursor c1" in result.output


def test_room_messages_stops_at_the_end_of_history(monkeypatch: pytest.MonkeyPatch) -> None:
    _paged(monkeypatch, [_page(["only"], cursor=None)])

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest"])

    assert result.exit_code == 0, result.output
    assert "more history" not in result.output


def test_room_messages_resumes_from_a_given_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _paged(monkeypatch, [_page(["older"], cursor=None)])

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--cursor", "c9"])

    assert result.exit_code == 0, result.output
    assert calls[0]["cursor"] == "c9"


def test_room_messages_json_carries_the_cursor_for_a_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A script drives the walk itself, so the cursor has to survive --json."""
    import json

    from mycelium.cli import app as root_app

    _paged(monkeypatch, [_page(["newest"], cursor="c1")])

    result = CliRunner().invoke(root_app, ["--json", "room", "messages", "msgtest"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["next_cursor"] == "c1"
    assert payload["has_more"] is True
    assert [m["content"] for m in payload["messages"]] == ["newest"]


def test_room_messages_all_resumes_from_a_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    """--all and --cursor compose: walk the rest of history from where I stopped."""
    calls = _paged(
        monkeypatch,
        [_page(["third"], cursor="c2"), _page(["fourth"], cursor=None)],
    )

    result = CliRunner().invoke(room_cmd.app, ["messages", "msgtest", "--cursor", "c1", "--all"])

    assert result.exit_code == 0, result.output
    assert [c["cursor"] for c in calls] == ["c1", "c2"]
    assert "third" in result.output
    assert "fourth" in result.output
