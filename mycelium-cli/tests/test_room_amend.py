"""Tests for `mycelium room amend` — revising a message you already sent.

The command wraps the generated ``amend_message`` client call. These patch that
call (and the config/room/client plumbing) and assert on the request it sends,
the rendering, and the refusal path.
"""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from mycelium import cli_options
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
    monkeypatch.setattr(cli_options, "resolve_room", lambda _c, _r=None: "amendtest")
    monkeypatch.setattr(cli_options, "resolve_handle", lambda _c, flag, **_k: flag or "growth")

    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = Mock(name="client")
    fake_cm.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: fake_cm)
    monkeypatch.setattr(_AMEND_SYNC, sync_fn)


def _revised(content: str = "TTL is 300s", replaced: str = "TTL is 30s", task: str | None = None):
    from mycelium_backend_client.models import MessageAmended

    stamp = datetime.datetime(2026, 6, 11, 21, 22, 56, tzinfo=datetime.UTC)
    return MessageAmended(
        id=uuid4(),
        sender_handle="growth",
        message_type="broadcast",
        content=content,
        created_at=stamp,
        edited_at=stamp,
        replaced=replaced,
        task=task,
        task_key="work/speed-up-the-board" if task else None,
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


def test_room_amend_shows_what_it_replaced_above_what_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common(monkeypatch, lambda **_kw: _revised(task="Speed up the board"))

    result = CliRunner().invoke(room_cmd.app, ["amend", "a1b2c3d4", "TTL is 300s"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "the thread of “Speed up the board”" in lines[0]
    assert "first posted" in lines[0]
    assert lines[1].split() == ["Replaced:", "TTL", "is", "30s"]
    assert lines[2].split() == ["With:", "TTL", "is", "300s"]
    # A correction shares its words with what it corrects: no warning.
    assert "little in common" not in result.output


def test_room_amend_warns_when_the_old_and_new_text_are_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mistake this exists for: a reply about one thing overwritten with another."""
    _patch_common(
        monkeypatch,
        lambda **_kw: _revised(
            content="Slide four's headline could read: nobody has this completely figured out.",
            replaced="The all-hands recording would have the exact word, if there's one to scrub through.",
        ),
    )

    result = CliRunner().invoke(room_cmd.app, ["amend", "a1b2c3d4", "Slide four's headline…"])

    assert result.exit_code == 0, result.output
    assert "Replaced: The all-hands recording" in result.output
    assert "little in common" in result.output


def test_room_amend_json_carries_the_replaced_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch, lambda **_kw: _revised())

    result = CliRunner().invoke(room_cmd.app, ["amend", "a1b2c3d4", "TTL is 300s", "--json"])

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["replaced"] == "TTL is 30s"
    assert body["content"] == "TTL is 300s"
    assert "task_key" in body


def test_a_long_message_shows_its_first_lines() -> None:
    old = "\n".join(f"line {i} of the original reply" for i in range(1, 8))
    lines = [
        line.text for line in room_cmd.amend_report(old, "line 1 of the original reply, fixed")
    ]
    assert lines[0].endswith("line 1 of the original reply")
    assert "… and 4 more lines" in lines[3]


def test_a_wrong_edit_shows_the_replaced_text_whole_to_put_it_back() -> None:
    """The warning says to restore from the text above, so all of it is there,
    paragraphs and all, exactly as it was."""
    old = "\n\n".join(
        f"Paragraph {i} about the all-hands recording and its slides." for i in range(1, 7)
    )
    old += "\n\n" + "x" * 150
    lines = [line.text for line in room_cmd.amend_report(old, "Slide four's headline, softened.")]
    replaced = [line[len("     Replaced: ") :] for line in lines[: len(old.splitlines())]]
    assert "\n".join(replaced) == old
    assert "replaced text above, in full" in lines[-1]


def test_room_amend_reports_a_message_it_cannot_revise(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal (not yours, or no such message) exits non-zero and says so."""
    _patch_common(monkeypatch, lambda **_kw: None)

    result = CliRunner().invoke(room_cmd.app, ["amend", "deadbeef", "nope"])

    assert result.exit_code == 1
    assert "deadbeef" in result.output
