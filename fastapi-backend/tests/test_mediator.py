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

import asyncio
import json
from typing import Any

import pytest

from app.services import aligner, l9, mediator
from tests.fakes import (
    FakeChannel,
    FakeManaged,
    FakeManager,
    FakePersister,
    fake_brain_factory,
    make_fake_llm,
)

_ROOM = "mediate-room"


def _engine(manager: FakeManager, **kw: Any) -> aligner.AlignerEngine:
    kw.setdefault("handle", "aligner")
    kw.setdefault("round_timeout_s", 0.2)
    kw.setdefault("poll_interval_s", 0.01)
    kw.setdefault("max_steps", 12)
    # The mediator brain is Pi in production; inject the deterministic fake here so
    # the SAO runs node-free and LLM-free.
    kw.setdefault("brain_factory", fake_brain_factory)
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
    into a fabricated concession.
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
    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)  # every prompt draws a reply
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

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
        persister = FakePersister()
        channel = FakeChannel(persister, reply_conf=0.9)
        managed = FakeManaged(_ROOM, "mycelium", channel, persister)
        manager = FakeManager(managed, ["growth", "risk", "aligner"])
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

    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "legal", "aligner"])

    await _engine(manager).mediate(_ROOM, scoped_participants=["growth", "risk"])

    prompted: set[str] = set()
    for s, _ in channel.sent:
        if s.header.kind == _Kind.exchange:
            prompted.update(envelope_recipients(s))
    # Only the named subset is addressed; @legal (a room member) is left out.
    assert prompted <= {"growth", "risk"}
    assert "legal" not in prompted
    assert prompted


@pytest.mark.asyncio
async def test_mediate_rejects_when_no_issues_discovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery that yields no structurable issues → a clean rejected verdict,
    still closing the episode (never hanging or raising)."""
    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk"])

    monkeypatch.setattr(mediator, "discover_issues", lambda *a, **k: [])

    verdict = await _engine(manager).mediate(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "rejected"
    assert manager.closed == [_ROOM]


# ── stage 0: the pre-negotiation term check (#680) ────────────────────────────


def _mismatch_llm(*, term: str = "done") -> Any:
    """A fake brain that reports one term mismatch, then behaves like the default."""
    base = make_fake_llm()

    def _llm(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        if "TERM MISMATCHES" in prompt:
            return json.dumps(
                {
                    "mismatches": [
                        {
                            "term": term,
                            "readings": {
                                "growth": "shipped to users",
                                "risk": "code merged, review pending",
                            },
                        }
                    ]
                }
            )
        return base(prompt, system=system, temperature=temperature)

    return _llm


def test_detect_term_mismatch_keeps_real_clashes_and_drops_the_rest() -> None:
    """A term two named participants read differently survives; a one-sided
    reading, an unknown handle, and a malformed entry are dropped rather than
    repaired — a fabricated mismatch would cost the room a whole round."""

    def llm(prompt: str, *, system: str = "", temperature: float = 0.0) -> str:
        return json.dumps(
            {
                "mismatches": [
                    {"term": "done", "readings": {"growth": "shipped", "risk": "merged"}},
                    {"term": "priority", "readings": {"growth": "urgent"}},  # one-sided
                    {"term": "blocked", "readings": {"growth": "waiting", "ghost": "stuck"}},
                    {"term": "", "readings": {"growth": "x", "risk": "y"}},
                    "not a dict",
                ]
            }
        )

    found = mediator.detect_term_mismatch({"growth": "a", "risk": "b"}, llm=llm)
    assert found == [{"term": "done", "readings": {"growth": "shipped", "risk": "merged"}}]


def test_detect_term_mismatch_empty_on_garbage_or_failure() -> None:
    """No mismatch is the safe answer: unparseable output and a brain that raises
    both mean the negotiation runs exactly as it would have."""
    positions = {"growth": "a", "risk": "b"}
    assert mediator.detect_term_mismatch(positions, llm=lambda *a, **k: "not json") == []
    assert mediator.detect_term_mismatch(positions, llm=lambda *a, **k: '{"mismatches":{}}') == []

    def boom(*_a: Any, **_k: Any) -> str:
        raise RuntimeError("brain down")

    assert mediator.detect_term_mismatch(positions, llm=boom) == []


def test_detect_term_mismatch_caps_the_clarifying_prompt() -> None:
    """More reported terms than the cap reads as over-reading, not a broken room."""

    def llm(*_a: Any, **_k: Any) -> str:
        return json.dumps(
            {
                "mismatches": [
                    {"term": f"t{i}", "readings": {"growth": "x", "risk": "y"}} for i in range(6)
                ]
            }
        )

    found = mediator.detect_term_mismatch({"growth": "a", "risk": "b"}, llm=llm)
    assert len(found) == mediator.MAX_TERM_MISMATCHES


def test_clarification_prompt_asks_for_a_definition_not_an_offer() -> None:
    prompt = mediator.clarification_prompt(
        "growth", [{"term": "done", "readings": {"growth": "shipped", "risk": "merged"}}]
    )
    assert "done" in prompt
    assert "shipped" in prompt and "merged" in prompt  # both readings shown, correctable
    assert "before any offers" in prompt


@pytest.mark.asyncio
async def test_mediate_injects_one_clarifying_round_on_term_mismatch() -> None:
    """A mismatch buys exactly ONE clarifying round — one turn per participant,
    before the first SAO step — and its answers reach issue discovery."""
    from app.services.l9_models import Kind as _Kind
    from app.services.persister import envelope_recipients

    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    seen: list[dict[str, str]] = []
    real_discover = mediator.discover_issues

    def spy_discover(task: str, positions: dict[str, str], **kw: Any) -> Any:
        seen.append(dict(positions))
        return real_discover(task, positions, **kw)

    engine = _engine(manager, brain_factory=lambda _ep: _mismatch_llm())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mediator, "discover_issues", spy_discover)
        verdict = await engine.mediate(_ROOM)

    assert verdict is not None
    ticks = [s for s, _ in channel.sent if s.header.kind == _Kind.exchange]
    clarify = [t for t in ticks if t.payload.data.get("action") == "clarify"]
    # One clarifying turn per participant, and one only — never a loop.
    assert [envelope_recipients(t)[0] for t in clarify] == ["growth", "risk"]
    assert all(t.payload.data["round"] == 0 for t in clarify)
    # It ran BEFORE the mechanism: the clarifying ticks precede every SAO tick.
    assert ticks[: len(clarify)] == clarify
    # And the answers are what discovery reads — the whole point of the round.
    assert seen and all("(clarified by @" in prose for prose in seen[0].values())


@pytest.mark.asyncio
async def test_mediate_records_the_term_check_on_the_episode() -> None:
    """The mismatch and each agent's answer land in the episode record, so an
    audit can see which words the room had to agree on before it could agree."""
    from app.services.filesystem import ensure_room_structure, get_room_dir

    room_dir = get_room_dir("term-record-room")
    ensure_room_structure(room_dir)

    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged("term-record-room", "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    await _engine(manager, brain_factory=lambda _ep: _mismatch_llm()).mediate("term-record-room")

    records = list((room_dir / "log" / "episodes").glob("*.md"))
    assert len(records) == 1
    body = records[0].read_text()
    assert "## Term Clarifications" in body
    assert "**done**" in body
    assert "read by @growth as: shipped to users" in body
    # The opening snapshot stays the prose the agents actually posted (#679) —
    # the clarification is recorded beside it, never folded back into it.
    assert "(clarified by @" not in body.split("## Term Clarifications")[0]


@pytest.mark.asyncio
async def test_mediate_without_term_mismatch_adds_no_round() -> None:
    """A room that shares its vocabulary negotiates exactly as before: no
    clarifying tick, no extra reply wait."""
    from app.services.l9_models import Kind as _Kind

    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    verdict = await _engine(manager).mediate(_ROOM)

    assert verdict is not None
    ticks = [s for s, _ in channel.sent if s.header.kind == _Kind.exchange]
    assert ticks  # the negotiation itself still ran
    assert all(t.payload.data.get("action") == "position" for t in ticks)


@pytest.mark.asyncio
async def test_term_check_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ALIGNER_TERM_CHECK=0`` skips the check entirely — not even the one call."""
    from app.config import settings

    monkeypatch.setattr(settings, "ALIGNER_TERM_CHECK", False)
    calls: list[str] = []

    def spy_detect(*a: Any, **k: Any) -> list[dict[str, Any]]:
        calls.append("called")
        return []

    monkeypatch.setattr(mediator, "detect_term_mismatch", spy_detect)

    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    await _engine(manager, brain_factory=lambda _ep: _mismatch_llm()).mediate(_ROOM)

    assert calls == []


@pytest.mark.asyncio
async def test_mediate_survives_a_failing_term_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken check costs the room nothing: the negotiation runs as if the
    vocabulary were shared, rather than failing the whole summon."""

    def boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise RuntimeError("brain down")

    monkeypatch.setattr(mediator, "detect_term_mismatch", boom)

    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    verdict = await _engine(manager).mediate(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "converged"


# ── #683: address the least-satisfied agent next (turn order) ─────────────────

_ISSUES_683 = [{"name": "cap", "options": ["30", "40", "50", "60"]}]
_OPTIONS_683 = {"cap": ["30", "40", "50", "60"]}


def _negotiation() -> mediator.MediatedNegotiation:
    """A MediatedNegotiation for turn-order tests; the seams it doesn't use here
    (fetch_prose/llm) are inert stubs since these tests never run the mechanism."""
    return mediator.MediatedNegotiation(
        issues=_ISSUES_683,
        cap=10,
        loop=asyncio.new_event_loop(),
        fetch_prose=lambda *a: None,  # type: ignore[arg-type,return-value]
        turn_timeout_s=1.0,
        llm=lambda *a, **k: "",
    )


def test_negmas_turn_order_seam_present() -> None:
    """Explainer guard: if NEGMAS renames ``next_negotitor_ids`` or drops
    ``state.current_offer``, this fails with a clear message instead of the
    least-satisfied ordering silently reverting to round-robin."""
    from negmas import SAOMechanism
    from negmas.outcomes import make_issue

    m = SAOMechanism(issues=[make_issue(values=["a", "b"], name="x")], n_steps=5)
    neg = _negotiation()
    m.add(mediator.LiveNegotiator("growth", neg))
    m.add(mediator.LiveNegotiator("risk", neg))
    assert callable(getattr(m, "next_negotitor_ids", None)), "NEGMAS turn-order seam moved"
    # Default (no standing offer): every negotiator, NEGMAS's round-robin.
    assert set(m.next_negotitor_ids()) == set(m.negotiator_ids)
    assert hasattr(m.state, "current_offer"), "NEGMAS state.current_offer seam moved"


def test_least_satisfied_order_puts_worst_first() -> None:
    order = ["g", "r"]
    id_to_handle = {"g": "growth", "r": "risk"}
    opening = {"growth": {"cap": "60"}, "risk": {"cap": "30"}}
    # Standing 40 sits next to risk's 30, far from growth's 60 → growth least happy.
    assert mediator.least_satisfied_order(
        order, id_to_handle, opening, {"cap": "40"}, _OPTIONS_683
    ) == [
        "g",
        "r",
    ]
    # Standing 50 flips it — now risk is furthest from satisfied.
    assert mediator.least_satisfied_order(
        order, id_to_handle, opening, {"cap": "50"}, _OPTIONS_683
    ) == [
        "r",
        "g",
    ]


def test_least_satisfied_order_falls_back_to_round_robin() -> None:
    order = ["g", "r"]
    id_to_handle = {"g": "growth", "r": "risk"}
    opening = {"growth": {"cap": "60"}, "risk": {"cap": "30"}}
    # No standing offer yet (round 0) → unchanged.
    assert mediator.least_satisfied_order(order, id_to_handle, opening, None, _OPTIONS_683) == order
    # No opening offers captured → unchanged.
    assert (
        mediator.least_satisfied_order(order, id_to_handle, {}, {"cap": "40"}, _OPTIONS_683)
        == order
    )
    # Unscoreable handles keep round-robin (stable, treated as satisfied).
    assert (
        mediator.least_satisfied_order(
            order, {"g": None, "r": None}, opening, {"cap": "40"}, _OPTIONS_683
        )
        == order
    )


def test_mechanism_addresses_least_satisfied_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The override composes NEGMAS order + negotiator→handle map + satisfaction."""
    neg = _negotiation()
    neg.opening_offers = {"growth": {"cap": "60"}, "risk": {"cap": "30"}}
    mech = mediator.build_mechanism(_ISSUES_683, ["growth", "risk"], neg, cap=10)
    monkeypatch.setattr(mech, "_standing_offer", lambda: {"cap": "40"})  # near risk's floor
    id_to_handle = {n.id: n.handle for n in mech.negotiators}
    ordered = [id_to_handle[i] for i in mech.next_negotitor_ids()]
    assert ordered[0] == "growth"


def test_mechanism_defaults_to_round_robin_before_first_offer() -> None:
    neg = _negotiation()  # no opening offers, no standing offer
    mech = mediator.build_mechanism(_ISSUES_683, ["growth", "risk"], neg, cap=10)
    assert set(mech.next_negotitor_ids()) == set(mech.negotiator_ids)


@pytest.mark.asyncio
async def test_least_satisfied_order_preserves_termination() -> None:
    """Reordering who is asked must not break termination: a converging run still
    stops at agreement, not the step cap (the anti-theatre invariant)."""
    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    verdict = await _engine(manager).mediate(_ROOM)

    assert verdict is not None
    assert verdict["header"]["subkind"] == "converged"
