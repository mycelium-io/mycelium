# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SAO mediator (app/services/mediator.py + aligner mediate).

Node-free and LLM-free: the LLM seam (``mediator.llm_sync``) is monkeypatched to
a deterministic prompt-keyed stub and the agents are simulated by the same fake
channel the aligner tests use. This exercises the anti-theatre property that matters —
**NEGMAS owns termination**: once the agents accept a standing offer the
mechanism *stops*, and the aligner emits a ``commit:converged`` carrying the
agreed ``issue = value`` map (the anti-theatre guarantee), never looping to the
step cap.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import aligner, l9, mediator
from tests.test_aligner import _FakeChannel, _FakeManaged, _FakeManager, _FakePersister

_ROOM = "mediate-room"


def _fake_llm(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
    """Deterministic stand-in for the mediator's LLM, keyed on the prompt.

    - discovery → one issue ``cap`` with three options;
    - a propose interpretation → counter to ``cap = 30``;
    - a respond interpretation → accept;
    - any broker framing → a short note.
    """
    if "identify the negotiable ISSUES" in prompt:
        return json.dumps({"issues": [{"name": "cap", "options": ["25", "30", "35"]}]})
    if "Interpret @" in prompt:
        if '"action":"counter"' in prompt:  # proposing schema
            return json.dumps({"action": "counter", "offer": {"cap": "30"}})
        return json.dumps({"action": "accept"})  # responding schema
    return "Everyone is close on the cap; let's lock 30 and move."


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mediator, "llm_sync", _fake_llm)


def _engine(manager: _FakeManager, **kw: Any) -> aligner.AlignerEngine:
    kw.setdefault("handle", "aligner")
    kw.setdefault("round_timeout_s", 0.2)
    kw.setdefault("poll_interval_s", 0.01)
    kw.setdefault("max_steps", 12)
    return aligner.AlignerEngine(manager, **kw)  # type: ignore[arg-type]


def test_discover_issues_parses_and_filters() -> None:
    """Well-formed issues survive; a degenerate single-option issue is dropped."""

    def llm(prompt: str, *, system: str = "", temperature: float = 0.0) -> str:
        return json.dumps(
            {
                "issues": [
                    {"name": "cap", "options": ["25", "30"]},
                    {"name": "bad", "options": ["x"]},
                ]
            }
        )

    issues = mediator.discover_issues("task", {"a": "pos"}, llm=llm)
    assert issues == [{"name": "cap", "options": ["25", "30"]}]


def test_discover_issues_empty_on_garbage() -> None:
    issues = mediator.discover_issues("task", {"a": "pos"}, llm=lambda *a, **k: "not json")
    assert issues == []


def test_interpret_fails_closed_on_empty_prose() -> None:
    """A silent agent (empty reply) must NEVER reach the interpreter LLM — else it
    hallucinates an offer and the negotiation 'converges' with no real input."""
    import asyncio

    calls: list[str] = []

    def spy_llm(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        calls.append(prompt)
        return json.dumps({"action": "accept"})

    neg = mediator.MediatedNegotiation(
        issues=[{"name": "cap", "options": ["25", "30"]}],
        cap=8,
        loop=asyncio.new_event_loop(),
        fetch_prose=lambda h, p, r: _never(),  # unused here
        turn_timeout_s=1.0,
        llm=spy_llm,
    )
    # Empty prose → empty reading, no LLM call (respond reads it as reject).
    assert neg.interpret("risk", "", proposing=False) == {}
    assert neg.interpret("risk", "   \n ", proposing=True) == {}
    assert calls == []  # the interpreter LLM was never invoked on silence


async def _never() -> str:  # pragma: no cover - placeholder coroutine
    return ""


def test_to_outcome_snaps_near_miss_but_refuses_out_of_grid() -> None:
    """to_outcome rescues a formatting near-miss ('30%'→'30') so a real move
    isn't dropped, but returns None for a value with no near-match (kept a reject,
    never fabricated into a wrong number)."""
    import asyncio

    neg = mediator.MediatedNegotiation(
        issues=[{"name": "tech", "options": ["25", "30", "35"]}],
        cap=8,
        loop=asyncio.new_event_loop(),
        fetch_prose=lambda h, p, r: _never(),
        turn_timeout_s=1.0,
    )
    assert neg.to_outcome({"tech": "30%"}) == ("30",)  # snapped
    assert neg.to_outcome({"Tech": "30"}) == ("30",)  # key snapped too
    assert neg.to_outcome({"tech": "27"}) is None  # no near-match → real reject


@pytest.mark.asyncio
async def test_mediate_terminates_at_agreement() -> None:
    """Agents that accept the standing offer → NEGMAS stops, verdict is converged
    with the agreed issue=value map, and the episode is opened then closed."""
    persister = _FakePersister()
    channel = _FakeChannel(persister, reply_conf=0.9)  # every prompt draws a reply
    managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = _FakeManager(managed, ["growth", "risk", "aligner"])

    verdict = await _engine(manager).mediate(_ROOM)

    assert verdict is not None
    assert verdict["header"]["kind"] == "commit"
    assert verdict["header"]["subkind"] == "converged"
    # The agreed issue=value map rides the envelope for plan_sync to compile.
    assert verdict["payload"]["data"]["assignments"] == {"cap": "30"}
    # Episode lifecycle: frozen membership opened, drained on close.
    assert manager.opened == [l9.episode_urn(_ROOM, "align")]
    assert manager.closed == [_ROOM]
    # Anti-theatre: it stopped the moment agreement was reached — the number of
    # agent turns (exchange prompts) is far below the step cap, not a full run.
    from app.services.l9_models import Kind

    prompts = [s for s, _ in channel.sent if s.header.kind == Kind.exchange]
    assert 0 < len(prompts) < 12
    # Every mediator turn-prompt AND the final verdict are recorded into the room
    # transcript/UI (via ingest_local), not just the SLIM log — so humans can
    # follow the negotiation live. One ingest per prompt, plus the verdict.
    assert len(persister.ingested) == len(prompts) + 1


@pytest.mark.asyncio
async def test_mediate_rejects_when_no_issues_discovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery that yields no structurable issues → a clean rejected verdict,
    still closing the episode (never hanging or raising)."""
    persister = _FakePersister()
    channel = _FakeChannel(persister, reply_conf=0.9)
    managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = _FakeManager(managed, ["growth", "risk"])

    monkeypatch.setattr(mediator, "discover_issues", lambda *a, **k: [])

    verdict = await _engine(manager).mediate(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "rejected"
    assert manager.closed == [_ROOM]
