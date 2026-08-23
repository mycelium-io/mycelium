"""Tests for `mycelium room amend` — revising a message you already sent.

The command wraps the generated ``amend_message`` client call. These patch that
call (and the config/room/client plumbing) and assert on the request it sends,
the rendering, and the refusal path.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from mycelium.commands import room as room_cmd

_AMEND_SYNC = (
    "mycelium_backend_client.api.messages"
    ".amend_message_api_rooms_room_name_messages_message_id_amend_post.sync"
)


def _patch_common(monkeypatch: pytest.MonkeyPatch, sync_fn) -> None:
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    fake_config.get_current_identity = lambda: "growth"
    monkeypatch.setattr(room_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(room_cmd, "_resolve_room", lambda _c, _r: "amendtest")

    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = Mock(name="client")
    fake_cm.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: fake_cm)
    monkeypatch.setattr(_AMEND_SYNC, sync_fn)


def _revised():
    from mycelium_backend_client.models import MessageRead

    stamp = datetime.datetime(2026, 6, 11, 21, 22, 56)  # noqa: DTZ001 — fixed for assertions
    return MessageRead(
        id=uuid4(),
        sender_handle="growth",
        message_type="broadcast",
        content="TTL is 300s",
        created_at=stamp,
        edited_at=stamp,
    )


def test_room_amend_sends_the_revision_for_the_named_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return _revised()

    _patch_common(monkeypatch, fake_sync)

    result = CliRunner().invoke(room_cmd.app, ["amend", "a1b2c3d4", "TTL is 300s"])

    assert result.exit_code == 0, result.output
    assert captured["message_id"] == "a1b2c3d4"
    assert captured["room_name"] == "amendtest"
    assert captured["body"].content == "TTL is 300s"
    assert captured["body"].sender_handle == "growth"
    assert "TTL is 300s" in result.output


def test_room_amend_uses_the_handle_option_over_the_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return _revised()

    _patch_common(monkeypatch, fake_sync)

    result = CliRunner().invoke(room_cmd.app, ["amend", "a1b2c3d4", "corrected", "--handle", "ops"])

    assert result.exit_code == 0, result.output
    assert captured["body"].sender_handle == "ops"


def test_room_amend_reports_a_message_it_cannot_revise(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal (not yours, or no such message) exits non-zero and says so."""
    _patch_common(monkeypatch, lambda **_kw: None)

    result = CliRunner().invoke(room_cmd.app, ["amend", "deadbeef", "nope"])

    assert result.exit_code == 1
    assert "deadbeef" in result.output
