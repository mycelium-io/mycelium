"""`mycelium room interrupt` and the note `respond` prints for a working member.

A plain @mention reaches a working member when its turn ends; its sender can
turn it into an interrupt after sending. These stub the generated client call
and check the request, what it says when it worked, and that a refusal says
the hub's own reason.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from typer.testing import CliRunner

from mycelium import cli_options
from mycelium.commands import room as room_cmd
from mycelium.commands.participate import working_note
from mycelium_backend_client.types import Response
from tests.hub_answers import ok, refused

_SYNC = (
    "mycelium_backend_client.api.messages"
    ".interrupt_with_message_api_rooms_room_name_messages_message_id_interrupt_post.sync_detailed"
)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """The calls made to the hub, answered by ``answer`` (set per test)."""
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    fake_config.get_current_identity = lambda: "lead"
    monkeypatch.setattr(room_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(room_cmd, "_resolve_room", lambda _c, _r: "checkout")
    monkeypatch.setattr(cli_options, "resolve_room", lambda _c, _r=None: "checkout")
    monkeypatch.setattr(cli_options, "resolve_handle", lambda _c, flag, **_k: flag or "lead")
    client = MagicMock()
    client.__enter__.return_value = Mock(name="client")
    client.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: client)
    calls: list[dict] = []
    answers: list[Response] = []

    def _answer(**kwargs):
        calls.append(kwargs)
        return answers.pop(0)

    monkeypatch.setattr(_SYNC, _answer)
    calls.append({"answers": answers})
    return calls


def _answers(sent: list[dict]) -> list[Response]:
    return sent[0]["answers"]


def test_it_interrupts_and_says_so(sent):
    from mycelium_backend_client.models import MessageInterrupted

    _answers(sent).append(
        ok(
            MessageInterrupted(
                by="lead", handle="builder", at=datetime.datetime(2026, 11, 6, tzinfo=datetime.UTC)
            ),
            201,
        )
    )
    result = CliRunner().invoke(room_cmd.app, ["interrupt", "7c1e9a04", "@builder"])
    assert result.exit_code == 0, result.output
    (call,) = sent[1:]
    assert call["room_name"] == "checkout"
    assert call["message_id"] == "7c1e9a04"
    assert call["body"].handle == "builder"
    assert call["body"].by == "lead"
    assert "@lead interrupted @builder with 7c1e9a04" in result.output
    assert "It stops, reads it, then carries on." in result.output


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (409, "@builder was already interrupted with 7c1e9a04. It's once per member per message."),
        (403, "Only @lead, who sent 7c1e9a04, can interrupt with it."),
        (
            422,
            "7c1e9a04 doesn't mention @conductor. To ask it now, send a message with @!conductor.",
        ),
    ],
)
def test_a_refusal_says_the_hub_s_reason(sent, status, detail):
    _answers(sent).append(refused(status, detail))
    result = CliRunner().invoke(room_cmd.app, ["interrupt", "7c1e9a04", "@builder"])
    assert result.exit_code == 1
    assert detail in result.output


def test_respond_names_the_command_for_a_working_member():
    assert working_note("checkout", "lead", "7c1e9a04", ["builder"]) == [
        "     @builder is working right now; it sees this when its turn ends.",
        "     If this changes what it is doing, interrupt it:",
        "       mycelium room interrupt 7c1e9a04 @builder --room checkout --as lead",
    ]
    two = working_note("checkout", "lead", "7c1e9a04", ["builder", "design"])
    assert (
        two[0]
        == "     @builder and @design are working right now; they see this when their turns end."
    )
    assert len(two) == 4
    assert working_note("checkout", "lead", "7c1e9a04", []) == []
    assert working_note("checkout", "lead", None, ["builder"]) == []
