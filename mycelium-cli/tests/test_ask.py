# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium ask``, and the answer as ``await`` shows it.

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
from mycelium.commands.participate import _answer_parts
from mycelium_backend_client.models import (
    AskAnswer,
    AskAnswerDecisionType0,
    AskAnswerKindType0,
    AwaitAskRead,
)
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


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """What each ``mycelium ask`` sent the hub."""
    bodies: list[dict] = []
    hub = install_stand_in_hub(monkeypatch)

    def answer(request: httpx.Request):
        bodies.append(json.loads(request.content))
        return _posted(request)

    hub.answer = answer
    return bodies


def test_the_cli_s_kinds_and_facts_are_the_contract_s() -> None:
    assert list(ask_cmd.KINDS) == CONTRACT["kinds"]
    assert list(ask_cmd.FACTS) == CONTRACT["ask_fields"]["facts"]
    assert CONTRACT["recommend_approve"] == ask_cmd.RECOMMEND_APPROVE
    assert set(ask_cmd._ASKED_TO) == set(CONTRACT["kinds"])


def test_only_the_question_is_needed(sent: list[dict]) -> None:
    result = runner.invoke(cli_app, ["ask", "--approve", "Turn Apple Pay on for everyone"])
    assert result.exit_code == 0, result.output
    assert sent == [
        {"handle": "builder", "question": "Turn Apple Pay on for everyone", "kind": "approve"}
    ]
    assert "asked @julia to approve, in checkout/work/apple-pay" in result.output


def test_the_facts_and_who_to_ask_are_sent(sent: list[dict]) -> None:
    result = runner.invoke(
        cli_app,
        ["ask", "--approve", "Merge it", "--undo", "Revert the merge", "--to", "@morgan"],
    )
    assert result.exit_code == 0, result.output
    assert sent[0]["undo"] == "Revert the merge"
    assert sent[0]["to"] == "morgan"
    assert "why" not in sent[0]


def test_a_bare_recommend_on_an_approve_recommends_it(sent: list[dict]) -> None:
    result = runner.invoke(cli_app, ["ask", "--approve", "Merge it", "--recommend"])
    assert result.exit_code == 0, result.output
    assert sent[0]["recommend"] == "approve"


def test_a_choose_sends_its_options_in_order_and_its_picks(sent: list[dict]) -> None:
    result = runner.invoke(
        cli_app,
        [
            "ask",
            "--choose",
            "Which first?",
            "--option",
            "Implement to the spec",
            "--option",
            "Copy their code",
            "--option",
            "Wait",
            "--multiple",
            "--recommend-option",
            "1,3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert sent[0]["kind"] == "choose"
    assert [o["label"] for o in sent[0]["options"]] == [
        "Implement to the spec",
        "Copy their code",
        "Wait",
    ]
    assert (sent[0]["multiple"], sent[0]["recommend"]) == (True, ["1", "3"])
    assert "asked @julia to pick" in result.output


def test_a_question_sends_its_draft_answer(sent: list[dict]) -> None:
    result = runner.invoke(
        cli_app, ["ask", "--question", "Where is it broken?", "--suggest", "The mechanics"]
    )
    assert result.exit_code == 0, result.output
    assert (sent[0]["kind"], sent[0]["suggest"]) == ("question", "The mechanics")
    assert "multiple" not in sent[0]


@pytest.mark.parametrize("flags", [[], ["--approve", "--question"]])
def test_it_says_what_kind_of_ask_it_needs(sent: list[dict], flags: list[str]) -> None:
    result = runner.invoke(cli_app, ["ask", *flags, "Merge it"])
    assert result.exit_code == 2
    assert "--approve, --choose or --question" in result.output
    assert sent == []


def test_a_refusal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: (
        422,
        {"detail": "A choose needs two or more options, each with a label"},
    )
    result = runner.invoke(cli_app, ["ask", "--choose", "Which?", "--option", "A"])
    assert result.exit_code == 1
    assert "two or more options" in result.output


def _answer(**fields) -> AwaitAskRead:
    return AwaitAskRead(
        prompt='Chose "Implement to the spec now" for "Which first?"\n\nNote: copy later',
        id="0" * 32,
        sender="jamie",
        answer=AskAnswer(ask="a1b2c3", by="jamie", at="2026-10-30T12:00:00+00:00", **fields),
    )


def test_await_says_whose_answer_it_is_when_someone_else_gave_it() -> None:
    read = _answer(
        kind=AskAnswerKindType0.CHOOSE, question="Which first?", for_="morgan", choices=["1"]
    )
    assert _answer_parts(read) == (" · answer to your ask, which you put to @morgan", "")
    mine = _answer(kind=AskAnswerKindType0.CHOOSE, question="Which first?", for_="jamie")
    assert _answer_parts(mine) == (" · answer to your ask", "")
    assert _answer_parts(AwaitAskRead(prompt="hi", id="0" * 32)) == ("", "")


def test_an_answer_from_an_older_hub_still_says_the_decision() -> None:
    read = _answer(decision=AskAnswerDecisionType0.DECLINED, reason="wait for the iPhone test")
    assert _answer_parts(read)[1] == (
        '\n\nAnswer to your ask a1b2c3: declined by @jamie, reason "wait for the iPhone test".'
    )
