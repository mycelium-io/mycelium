# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Verify the NEGMAS mediation core (mycelium.engine.mediator) runs.

Node-free / LLM-free: a deterministic prompt-keyed fake brain and a fake
``fetch_prose`` drive the whole NEGMAS SAO loop. Asserts the anti-theatre
property — the mechanism terminates at agreement below the step cap (it does
not spin to the cap), and the agreed ``issue = value`` map is recoverable.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("negmas", reason="negmas not installed; install mycelium[engine]")

from mycelium.engine import mediator


def _fake_brain(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
    if "identify the negotiable ISSUES" in prompt:
        return json.dumps({"issues": [{"name": "cap", "options": ["25", "30", "35"]}]})
    if "Interpret @" in prompt:
        if '"action":"counter"' in prompt:  # proposing schema
            return json.dumps({"action": "counter", "offer": {"cap": "30"}})
        return json.dumps({"action": "accept"})  # responding schema
    return "Everyone is close on the cap; let's lock 30."


def test_extract_json_tolerates_fences_and_prose() -> None:
    """The extractor must survive how chat models actually wrap JSON."""
    ex = mediator._extract_json
    # bare object
    assert ex('{"action":"accept"}') == {"action": "accept"}
    # ```json code fence with surrounding prose
    fenced = (
        'Here is my reading:\n```json\n{"action": "counter", "offer": {"cap": "30"}}\n```\nDone.'
    )
    assert ex(fenced) == {"action": "counter", "offer": {"cap": "30"}}
    # a stray brace in preamble must not break the greedy span
    assert ex('I considered {a few options} and chose: {"action":"reject"}') == {"action": "reject"}
    # no JSON at all → empty dict, never a crash
    assert ex("I accept the offer on the table.") == {}


def test_discover_issues_parses_and_filters() -> None:
    issues = mediator.discover_issues(
        "task",
        {"a": "I want 30", "b": "I want 25"},
        llm=lambda *a, **k: json.dumps(
            {
                "issues": [
                    {"name": "cap", "options": ["25", "30"]},
                    {"name": "bad", "options": ["x"]},
                ]
            }
        ),
    )
    assert issues == [{"name": "cap", "options": ["25", "30"]}]


@pytest.mark.asyncio
async def test_core_terminates_at_agreement() -> None:
    """The ported loop drives NEGMAS to agreement and STOPS below the cap."""
    issues = [{"name": "cap", "options": ["25", "30", "35"]}]
    cap = 12
    prompts_sent: list[str] = []

    async def fetch_prose(handle: str, prompt: str, round_n: int) -> str:
        prompts_sent.append(handle)
        return "I accept 30."  # fake agent reply; the fake brain maps it

    neg = mediator.MediatedNegotiation(
        issues=issues,
        cap=cap,
        loop=asyncio.get_running_loop(),
        fetch_prose=fetch_prose,
        turn_timeout_s=1.0,
        llm=_fake_brain,
    )
    mech = mediator.build_mechanism(issues, ["growth", "risk"], neg, cap=cap)
    await asyncio.to_thread(mech.run)

    assignments = mediator.agreement_assignments(mech, neg.names)
    assert assignments == {"cap": "30"}  # agreed value recovered
    # Anti-theatre: it stopped at agreement — far fewer turns than the step cap.
    assert 0 < len(prompts_sent) < cap
