# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium ask --approve``, and the answer as ``await`` shows it.

Node-free: the hub is a stand-in that records what the command sends.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import cli_options
from mycelium.cli import app as cli_app
from mycelium.commands import ask as ask_cmd
from mycelium.commands.participate import _decision_line
from mycelium_backend_client.models import AskAnswer, AskAnswerDecision, AwaitAskRead
from tests.conftest import install_stand_in_hub

runner = CliRunner()
ROOM = "checkout"
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "approvals.json").read_text()
)


@pytest.fixture(autouse=True)
def _shared_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_options, "resolve_room", lambda _c, flag=None: flag or ROOM)
    monkeypatch.setattr(cli_options, "resolve_handle", lambda _c, flag, **_k: flag or "builder")


def _posted(request: httpx.Request) -> tuple[int, dict]:
    body = json.loads(request.content)
    ask = {"id": "a1b2c3", "kind": body["kind"], "to": body.get("to") or "julia"}
    ask |= {k: body[k] for k in ("question", *ask_cmd.FACTS) if body.get(k)}
    return 201, {
        "room": ROOM,
        "task": "work/apple-pay",
        "episode": f"urn:ioc:mycelium:episode:{ROOM}:apple-pay",
        "message_id": "00000000-0000-0000-0000-000000000000",
        "ask": ask,
    }


def test_the_cli_s_kinds_and_facts_are_the_contract_s() -> None:
    assert list(ask_cmd.KINDS) == CONTRACT["kinds"]
    assert list(ask_cmd.FACTS) == CONTRACT["ask_fields"]["optional"]


def test_only_the_question_is_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    hub = install_stand_in_hub(monkeypatch)

    def answer(request: httpx.Request):
        sent.append(json.loads(request.content))
        return _posted(request)

    hub.answer = answer
    result = runner.invoke(cli_app, ["ask", "--approve", "Turn Apple Pay on for everyone"])
    assert result.exit_code == 0, result.output
    assert sent == [
        {"handle": "builder", "question": "Turn Apple Pay on for everyone", "kind": "approve"}
    ]
    assert "asked @julia to approve, in checkout/work/apple-pay" in result.output


def test_the_facts_and_who_to_ask_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    hub = install_stand_in_hub(monkeypatch)

    def answer(request: httpx.Request):
        sent.append(json.loads(request.content))
        return _posted(request)

    hub.answer = answer
    result = runner.invoke(
        cli_app,
        ["ask", "--approve", "Merge it", "--undo", "Revert the merge", "--to", "@morgan"],
    )
    assert result.exit_code == 0, result.output
    assert sent[0]["undo"] == "Revert the merge"
    assert sent[0]["to"] == "morgan"
    assert "why" not in sent[0]


def test_it_says_what_kind_of_ask_it_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stand_in_hub(monkeypatch)
    result = runner.invoke(cli_app, ["ask", "Merge it"])
    assert result.exit_code == 2
    assert "--approve" in result.output


def test_a_refusal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: (422, {"detail": "No task to ask in: name it with --task"})
    result = runner.invoke(cli_app, ["ask", "--approve", "Merge it"])
    assert result.exit_code == 1
    assert "--task" in result.output


def test_await_shows_the_decision_beside_the_message() -> None:
    read = AwaitAskRead(
        prompt="Declined: wait for the iPhone test",
        id="0" * 32,
        sender="julia",
        answer=AskAnswer(
            ask="a1b2c3",
            decision=AskAnswerDecision.DECLINED,
            by="julia",
            at="2026-10-30T12:00:00+00:00",
            reason="wait for the iPhone test",
        ),
    )
    assert _decision_line(read) == (
        '\n\nAnswer to your ask a1b2c3: declined by @julia, reason "wait for the iPhone test".'
    )
    assert _decision_line(AwaitAskRead(prompt="hi", id="0" * 32)) == ""
