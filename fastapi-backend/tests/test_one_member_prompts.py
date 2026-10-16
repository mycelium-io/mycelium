# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A prompt code builds for one member mentions that member alone.

Nothing strips ``@`` from what is posted (``asks.py``), so wherever code writes
the text, writing a bare ``@`` only for whoever is asked is the code's job: a
turn to alice that names bob bare would wake bob in the middle of it. These
check each prompt the aligner and the conductor build for one member.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import mediator, protocols
from app.services.persister import parse_mentions

MISMATCHES = [{"term": "uptime", "readings": {"alice": "99.9%", "bob": "business hours"}}]


def _negotiation() -> mediator.MediatedNegotiation:
    return mediator.MediatedNegotiation(
        issues=[{"name": "cap", "options": ["25", "30"]}],
        cap=8,
        loop=asyncio.new_event_loop(),
        fetch_prose=lambda *_a: None,  # never fetched
        turn_timeout_s=1.0,
        llm=lambda *_a, **_k: "",
    )


def test_the_clarifying_round_asks_only_its_member():
    prompt = mediator.clarification_prompt("alice", MISMATCHES)
    assert parse_mentions(prompt) == ["alice"]
    assert "@~bob seems to mean business hours" in prompt


@pytest.mark.parametrize("proposing", [True, False])
def test_a_step_asks_only_its_member(proposing: bool):
    neg = _negotiation()
    prompt = neg._prompt_for("alice", ("25",), proposing, "both are close", 2)
    assert parse_mentions(prompt) == ["alice"]


def test_asking_again_about_its_own_offer_asks_only_its_member(monkeypatch):
    neg = _negotiation()
    asked: list[str] = []
    monkeypatch.setattr(neg, "_ask", lambda _h, prompt, _r: asked.append(prompt) or "")
    neg.confirm_own_offer("alice", ("25",), 3)
    (prompt,) = asked
    assert parse_mentions(prompt) == ["alice"]


def test_the_history_the_broker_is_shown_names_nobody_bare():
    neg = _negotiation()
    proposer = mediator.RemoteAgentNegotiator("alice", neg)
    neg.agent_move = lambda *_a, **_k: ""  # ty: ignore[invalid-assignment]
    neg.interpret = lambda *_a, **_k: {}  # ty: ignore[invalid-assignment]

    class _State:
        step = 1
        current_offer = ("25",)

    proposer.respond(_State())
    assert "@~alice" in neg._history_block()
    assert parse_mentions(neg._history_block()) == []


@pytest.mark.parametrize("name", protocols.builtin_names())
def test_no_built_in_flow_step_names_anyone_bare(name: str):
    # A step's prompt goes to the member the step addresses; what the flow
    # itself writes names members by role, never with a bare @.
    flow = protocols.builtin(name)
    assert flow is not None
    for step in flow.steps:
        assert parse_mentions(step.prompt) == [], f"{name}/{step.id}"
