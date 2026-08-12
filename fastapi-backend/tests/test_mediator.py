# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SAO mediator (app/services/mediator.py + aligner mediate).

Node-free and LLM-free: the mediator's brain is injected as a deterministic
prompt-keyed stub (via the aligner's ``brain_factory``) and the agents are
simulated by the same fake channel the aligner tests use. This exercises the
anti-theatre property that matters —
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


def _engine(manager: _FakeManager, **kw: Any) -> aligner.AlignerEngine:
    kw.setdefault("handle", "aligner")
    kw.setdefault("round_timeout_s", 0.2)
    kw.setdefault("poll_interval_s", 0.01)
    kw.setdefault("max_steps", 12)
    # The mediator brain is Pi in production; inject the deterministic fake here so
    # the SAO runs node-free and LLM-free.
    kw.setdefault("brain_factory", lambda _episode: _fake_llm)
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
    """to_outcome rescues a formatting near-miss ('30%'→'30') and snaps a real
    numeric counter that lands between grid points to the nearest option ('27'→'25',
    '28'→'30'), so a genuine move isn't dropped — but still returns None for a value
    genuinely off the grid, never fabricated into a wrong number."""
    import asyncio

    neg = mediator.MediatedNegotiation(
        issues=[{"name": "tech", "options": ["25", "30", "35"]}],
        cap=8,
        loop=asyncio.new_event_loop(),
        fetch_prose=lambda h, p, r: _never(),
        turn_timeout_s=1.0,
        llm=lambda *a, **k: "",  # unused by to_outcome, but the brain is now required
    )
    assert neg.to_outcome({"tech": "30%"}) == ("30",)  # formatting near-miss snapped
    assert neg.to_outcome({"Tech": "30"}) == ("30",)  # key snapped too
    assert neg.to_outcome({"tech": "27"}) == ("25",)  # between grid points → nearest
    assert neg.to_outcome({"tech": "28"}) == ("30",)  # nearest is 30, not dropped
    assert neg.to_outcome({"tech": "100"}) is None  # genuinely off-grid → real reject


def test_propose_holds_own_line_not_the_table_when_unreadable() -> None:
    """THE phantom-convergence guard at the proposer seam.

    When an agent's proposing move can't be read onto the grid (here an off-grid
    '999'), it must be recorded as holding ITS OWN last line — never the standing
    offer on the table. Adopting the table's number silently converts a rejection
    into a fabricated concession, which is exactly how the negotiation used to
    'converge' on a value nobody actually offered.
    """
    import asyncio

    def llm(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        return json.dumps({"action": "counter", "offer": {"cap": "999"}})  # off-grid

    neg = mediator.MediatedNegotiation(
        issues=[{"name": "cap", "options": ["20", "25", "30", "35", "40"]}],
        cap=8,
        loop=asyncio.new_event_loop(),
        fetch_prose=lambda h, p, r: _never(),
        turn_timeout_s=1.0,
        llm=llm,
    )
    # @risk already established a real line at 25 on an earlier turn.
    neg.set_last_offer("risk", ("25",))
    # Bypass the SLIM/loop bridge — feed canned prose directly.
    neg.agent_move = lambda *a, **k: "I counter with 999"  # type: ignore[method-assign]

    class _State:
        current_offer = ("40",)  # the number sitting on the table
        step = 2

    outcome = mediator.LiveNegotiator("risk", neg).propose(_State())
    assert outcome == ("25",)  # held its OWN prior line
    assert outcome != _State.current_offer  # NOT the table's 40 — no phantom

    # And with no prior line at all, it falls to its opening stance (grid min),
    # still never the counterpart's standing offer.
    fresh = mediator.LiveNegotiator("newbie", neg).propose(_State())
    assert fresh == ("20",)
    assert fresh != _State.current_offer


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
    # Episode lifecycle: frozen membership opened, drained on close. Each convening
    # gets a unique episode id (no longer the hardcoded "align"), so assert the
    # shape — one room-scoped episode opened — not a fixed suffix.
    assert len(manager.opened) == 1
    assert manager.opened[0].startswith(l9.episode_urn(_ROOM, ""))
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
async def test_two_convenings_write_distinct_episode_records() -> None:
    """Episodes are distinct sessions: two ``@aligner`` convenings in the SAME room
    must produce TWO distinct ``log/episodes/{id}.md`` records, not clobber one.

    Guards the fix that replaced the hardcoded ``short_id="align"`` (every
    negotiation overwrote the single ``align.md``) with a unique id per convening.
    Exercises the real ``write_episode_record`` path against the temp data dir.
    """
    from app.services.filesystem import ensure_room_structure, get_room_dir

    room_dir = get_room_dir(_ROOM)
    ensure_room_structure(room_dir)

    async def _convene() -> str:
        persister = _FakePersister()
        channel = _FakeChannel(persister, reply_conf=0.9)
        managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
        manager = _FakeManager(managed, ["growth", "risk", "aligner"])
        verdict = await _engine(manager).mediate(_ROOM)
        assert verdict is not None
        return manager.opened[0]

    ep1 = await _convene()
    ep2 = await _convene()

    # Distinct episode URNs on the wire ...
    assert ep1 != ep2
    assert ep1.startswith(l9.episode_urn(_ROOM, ""))
    # ... and two distinct records on disk (no clobber of a single record).
    records = sorted(p.name for p in (room_dir / "log" / "episodes").glob("*.md"))
    assert len(records) == 2, records


@pytest.mark.asyncio
async def test_mediate_scopes_to_named_participants() -> None:
    """A scoped summon (``@aligner @growth``) negotiates only the named subset —
    the other room members are never addressed by the mediator."""
    from app.services.l9_models import Kind as _Kind
    from app.services.persister import envelope_recipients

    persister = _FakePersister()
    channel = _FakeChannel(persister, reply_conf=0.9)
    managed = _FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = _FakeManager(managed, ["growth", "risk", "legal", "aligner"])

    await _engine(manager).mediate(_ROOM, scoped_participants=["growth", "risk"])

    prompted: set[str] = set()
    for s, _ in channel.sent:
        if s.header.kind == _Kind.exchange:
            prompted.update(envelope_recipients(s))
    # Only the named subset is addressed; @legal (a room member) is left out.
    assert prompted <= {"growth", "risk"}
    assert "legal" not in prompted
    assert prompted  # the scoped negotiation actually ran


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
