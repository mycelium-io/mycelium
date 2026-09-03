# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The SAO mediator — the aligner as a *driver* of a real negotiation.

This module actively drives the NEGMAS SAO negotiation and terminates at
unanimity, rather than only grading a finished transcript after the fact.

An LLM mediator reads natural-language agent
chatter, maps it onto a NEGMAS **Stacked Alternating Offers** mechanism, and
**NEGMAS owns termination** — the mechanism stops the instant everyone accepts
the standing offer. Convergence needs **memory + a brokering mediator + BATNA**
(the "camp counselor"); bare-offer relaying to stateless agents deadlocks. This
module runs that loop *live over SLIM*
against real worker agents, still driven by the reserved ``@aligner`` handle.

**The Node/Python-free seam.** NEGMAS is a synchronous Python mechanism; SLIM I/O
is async on the backend event loop. ``mech.run()`` runs on a worker thread so
NEGMAS keeps ownership of turn order and termination; each negotiator blocks
for its own agent's real reply: the
negotiator's ``propose``/``respond`` bridge back to the loop with
``run_coroutine_threadsafe`` to publish an ``@``-addressed prompt and collect the
reply the persister records, then interpret the prose in-thread. NEGMAS keeps
full ownership of proposer rotation and the unanimity stop; we only supply each
agent's move when NEGMAS asks for it. LLM calls (discover/broker/interpret) run
synchronously in-thread against the injected Pi llm_session (see ``pi_session``).

The mediator is deliberately *interpretation over the agents' prose*: agents are
never required to emit structured markers. The mediator restates its reading into
the transcript ("recording @growth as counter → 35% tech") so a misread is
visible and correctable in-band.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from negmas import SAOMechanism, make_issue
from negmas.sao import ResponseType, SAONegotiator

from app.services.offer_snap import snap_offer

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

# The mediator's issue-discovery runs at temperature 0 for stable JSON parsing.
_DISCOVER_TEMPERATURE = 0.0

# Terms the pre-negotiation check will ask about in one clarifying round. A
# mismatch list longer than this is a signal the check is over-reading the prose,
# not that the room shares five broken words; the clarifying prompt stays short.
MAX_TERM_MISMATCHES = 3

# Negotiation stance appended to every agent-facing prompt: concede where you
# genuinely can, and hold the limits that matter. A durable agreement reflects
# true position, not capitulation.
_BATNA = (
    "Negotiate in good faith toward a workable agreement: concede where you genuinely can, "
    "and hold the limits that actually matter to you. Do not abandon a real hard line just to "
    "close — a durable agreement reflects your true position, not capitulation."
)


def _extract_json(text: str) -> dict[str, Any]:
    """First JSON object embedded in a model response (empty dict on miss).

    Robust to the ways a chat model wraps JSON: a ```` ```json ```` code fence,
    a sentence of preamble, or trailing commentary. We scan for each ``{`` and
    let :meth:`json.JSONDecoder.raw_decode` consume the longest valid object
    starting there — unlike a greedy ``\\{.*\\}`` regex, which spans from the
    first brace to the *last* brace anywhere in the text and so is broken by any
    stray brace in prose. The first ``{`` that yields a dict wins.
    """
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def detect_term_mismatch(
    positions: dict[str, str], *, llm: Callable[..., str]
) -> list[dict[str, Any]]:
    """Mediator stage 0 — do two agents use the same word to mean different things?

    Reads the opening prose *before* any offers and returns the terms two or more
    participants use in materially different senses, as
    ``[{"term": str, "readings": {handle: meaning}}]``. An empty list — the
    common case — means the negotiation proceeds exactly as it would have.

    A term mismatch is not a disagreement: two agents wanting a different *value*
    for the same word is the negotiation itself. What this catches is the case
    that survives it — an agreement whose words each side reads differently, so
    the room converges on prose while still talking past each other.

    Faithful, never fabricated (the aligner's standing rule): a reported mismatch
    must name a real participant on both sides and quote a reading per agent, and
    anything that fails those checks is dropped rather than repaired. Fail-soft on
    an LLM error or garbage output — no mismatch, no clarifying round.
    """
    roster = {handle.strip().lower(): handle for handle in positions}
    opening = "\n".join(f"@{handle}: {prose}" for handle, prose in positions.items())
    try:
        out = _extract_json(
            llm(
                "You are a negotiation mediator reading the opening positions BEFORE any "
                "offers are made. Find TERM MISMATCHES: a word or phrase that two or more "
                "agents both use but MEAN DIFFERENTLY, so an agreement written with that word "
                "would hide a disagreement instead of settling it.\n"
                "Report a mismatch ONLY when you can quote each agent's own sense of the term "
                "from their text. Wanting a different VALUE for the same term is NOT a "
                "mismatch — that is the negotiation. An empty list is the normal answer; do "
                "not invent one.\n\n"
                f"POSITIONS:\n{opening}\n\n"
                'Return ONLY JSON: {"mismatches":[{"term":"the word",'
                '"readings":{"handle":"what that agent means by it"}}]}',
                system="Strict JSON. Report only genuine same-word-different-meaning clashes; "
                'prefer {"mismatches":[]} over a speculative one.',
                temperature=_DISCOVER_TEMPERATURE,
            )
        )
    except Exception:
        logger.warning("mediator term check failed; continuing without a clarifying round")
        return []
    raw = out.get("mismatches")
    if not isinstance(raw, list):
        return []
    clean: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        term = item.get("term")
        readings = item.get("readings")
        if not isinstance(term, str) or not term.strip() or not isinstance(readings, dict):
            continue
        # Keep only readings attributed to a real participant, and only a term at
        # least two of them are on: a one-sided "mismatch" is just one agent's
        # definition, and an unknown handle is a fabrication.
        named = {
            roster[str(h).strip().lower()]: str(v).strip()
            for h, v in readings.items()
            if str(h).strip().lower() in roster and str(v).strip()
        }
        if len(named) < 2:
            continue
        clean.append({"term": term.strip(), "readings": named})
        if len(clean) == MAX_TERM_MISMATCHES:
            break
    return clean


def clarification_prompt(handle: str, mismatches: list[dict[str, Any]]) -> str:
    """The one clarifying turn's prompt — deterministic prose, no offer requested.

    Shows the agent how the room is reading each contested term (including its own
    reading, so a misread is correctable in-band, the same way the mediator
    restates its SAO readings) and asks only for a definition.
    """
    terms = "\n".join(
        f'- "{m["term"]}" — '
        + "; ".join(f"@{h} seems to mean {reading}" for h, reading in m["readings"].items())
        for m in mismatches
    )
    return (
        f"@{handle} — clarifying round, before any offers. The opening positions use the same "
        f"term in what look like different senses:\n\n{terms}\n\n"
        "State plainly what YOU mean by each term (one sentence each), and correct the reading "
        "above if it has you wrong. Do not make or accept an offer yet — this round only fixes "
        "the vocabulary so the agreement means the same thing to everyone."
    )


def discover_issues(
    task: str, positions: dict[str, str], *, llm: Callable[..., str]
) -> list[dict[str, Any]]:
    """Mediator stage 1 — read opening prose into negotiable issues + options.

    ``llm`` is the mediator's llm_session (the Pi agent), supplied by the caller — there
    is no built-in default. Returns a list of ``{"name": snake_case, "options":
    [token, ...]}``. An empty/degenerate result (fewer than one issue) is a signal
    to the caller to bail to a rejected verdict rather than build an empty mechanism.
    """
    opening = "\n".join(f"@{handle}: {prose}" for handle, prose in positions.items())
    out = _extract_json(
        llm(
            "You are a negotiation mediator. From the task and each agent's opening position, "
            "identify the negotiable ISSUES and their discrete OPTIONS.\n"
            "Only include issues an agent actually raised — do NOT invent extra dimensions.\n"
            "For a NUMERIC/quantity issue, the options MUST be an evenly-spaced grid that "
            "spans BOTH agents' stated values AND the space between them, so any middle "
            "compromise is representable (e.g. positions 20 and 40 → options 20,25,30,35,40). "
            "For a categorical issue, give 3-4 concrete choices.\n\n"
            f"TASK: {task}\n\nPOSITIONS:\n{opening}\n\n"
            'Return ONLY JSON: {"issues":[{"name":"snake_case","options":["v1","v2"]}]}',
            system="Strict JSON. Options are short concrete tokens (e.g. '30' or 'on'). "
            "Numeric issues get a full evenly-spaced range, not just the endpoints.",
            temperature=_DISCOVER_TEMPERATURE,
        )
    )
    issues = out.get("issues")
    if not isinstance(issues, list):
        return []
    clean: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        name = issue.get("name")
        options = issue.get("options")
        if isinstance(name, str) and name and isinstance(options, list) and len(options) >= 2:
            clean.append({"name": name, "options": [str(o) for o in options]})
    return clean


class MediatedNegotiation:
    """Run context for one SAO negotiation: history, LLM seams, SLIM bridge.

    Holds the per-negotiation running history (the "memory" a persistent agent
    session provides), the injectable ``llm`` and ``fetch_prose`` seams (so tests
    drive the whole NEGMAS loop with no live LLM or channel), and the event loop
    the negotiator threads bridge back to for SLIM I/O.
    """

    def __init__(
        self,
        *,
        issues: list[dict[str, Any]],
        cap: int,
        loop: asyncio.AbstractEventLoop,
        fetch_prose: Callable[[str, str, int], Coroutine[Any, Any, str]],
        turn_timeout_s: float,
        llm: Callable[..., str],
        on_reading: Callable[[str, dict[str, Any], bool], None] | None = None,
    ) -> None:
        self._issues = issues
        self._names = [i["name"] for i in issues]
        self._options = {i["name"]: i["options"] for i in issues}
        self._cap = cap
        self._loop = loop
        self._fetch_prose = fetch_prose
        self._turn_timeout_s = turn_timeout_s
        self._llm = llm
        self._on_reading = on_reading
        self.history: list[str] = []
        # Last outcome we actually *read* from each proposer, so an unreadable
        # later turn holds that agent's own line instead of fabricating one.
        self._last_offer: dict[str, tuple[str, ...]] = {}
        # Each agent's first concrete offer (issue -> value) — its opening ask.
        # Used by satisfaction-ordering to score against the standing offer;
        # captured once per agent, on its first readable proposal.
        self.opening_offers: dict[str, dict[str, str]] = {}

    @property
    def issue_options(self) -> dict[str, list[str]]:
        """Each issue's ordered options as strings (the grid satisfaction scores on)."""
        return {n: [str(o) for o in self._options[n]] for n in self._names}

    def note_opening_offer(self, handle: str, offer: dict[str, Any]) -> None:
        """Record ``handle``'s opening ask the first time it makes a readable offer."""
        if offer:
            self.opening_offers.setdefault(handle, {k: str(v) for k, v in offer.items()})

    # -- mediator LLM stages (run in the negotiator thread) --

    def _history_block(self) -> str:
        return "\n".join(self.history[-12:]) if self.history else "(negotiation just started)"

    def broker(self, offer: tuple[Any, ...] | None, round_n: int) -> str:
        """The mediator's per-turn framing — where everyone stands + a nudge."""
        order = ", ".join(self._names)
        try:
            return self._llm(
                f"You are the negotiation mediator (a neutral camp counselor). It is step "
                f"{round_n} of {self._cap}. Issue order: {order}. Offer on the table: {offer}.\n\n"
                f"History so far:\n{self._history_block()}\n\nWrite 2 sentences to the group: "
                "summarize where each agent stands, name who has hit a genuine hard limit, and "
                "surface the space that's still open between them. Be concrete and fair, not "
                "preachy — do not pressure anyone to abandon a real limit.",
                system="You are a fair mediator who wants a durable agreement, not to favor anyone.",
            )
        except Exception:
            logger.warning("mediator broker LLM failed (step %d); continuing without note", round_n)
            return ""

    def interpret(self, handle: str, prose: str, *, proposing: bool) -> dict[str, Any]:
        """Map an agent's natural-language move into a structured SAO action.

        **Fail closed on silence.** An empty ``prose`` means the agent never
        replied within the round window (``_slim_turn`` timeout). Feeding ``""``
        to the interpreter LLM makes it *hallucinate* a full offer — so a
        negotiation could "converge" with no real agent input. Instead, empty
        prose is a deterministic no-op: an empty reading
        that ``respond`` reads as a reject and ``propose`` folds into the standing
        offer. Never invent a position for a silent agent.
        """
        if not prose.strip():
            logger.info(
                "mediator: @%s gave no reply within the round window — "
                "treating as reject/hold (not interpreting)",
                handle,
            )
            empty: dict[str, Any] = {}
            if self._on_reading is not None:
                self._on_reading(handle, empty, proposing)
            return empty
        order = ", ".join(self._names)
        schema = (
            '{"action":"counter","offer":{"<issue>":"<option>", ...}}'
            if proposing
            else '{"action":"accept"} OR {"action":"reject"}'
        )
        space = "; ".join(f"{n}={self._options[n]}" for n in self._names)
        try:
            reading = _extract_json(
                self._llm(
                    f"Interpret @{handle}'s move into a structured SAO action.\n"
                    f"Issues (order {order}): {space}\n\n"
                    f'@{handle} said:\n"""{prose}"""\n\n'
                    f"Return ONLY JSON: {schema}. Every offer value MUST be one of that issue's "
                    "options.",
                    system="Strict JSON mapping a negotiator's words to an SAO action.",
                    temperature=_DISCOVER_TEMPERATURE,
                )
            )
        except Exception:
            logger.warning("mediator interpret LLM failed for @%s; treating as reject", handle)
            reading = {}
        if self._on_reading is not None:
            self._on_reading(handle, reading, proposing)
        return reading

    # -- the SLIM bridge (blocks the negotiator thread on the real agent reply) --

    def _prompt_for(
        self, handle: str, offer: tuple[Any, ...] | None, proposing: bool, note: str, round_n: int
    ) -> str:
        space = "; ".join(f"{n} ∈ {{{', '.join(self._options[n])}}}" for n in self._names)
        order = ", ".join(self._names)
        role = (
            f"It is your turn to PROPOSE. Current standing offer: {offer}. State the offer you "
            "want (a value per issue) with one line of why."
            if proposing
            else f"The offer on the table is {offer} (issue order: {order}). ACCEPT it or REJECT "
            "it, with one line of why."
        )
        return (
            f"@{handle} — step {round_n}. Issue space: {space}.\n\n"
            f"MEDIATOR: {note}\n\n{role} (2 sentences max.)\n\n{_BATNA}"
        )

    def agent_move(
        self, handle: str, offer: tuple[Any, ...] | None, *, proposing: bool, round_n: int
    ) -> str:
        """Broker → prompt the real agent over SLIM → return its prose reply.

        Runs in the NEGMAS worker thread; the SLIM publish/collect is bridged to
        the backend event loop and this call blocks on the agent's real reply.
        """
        note = self.broker(offer, round_n)
        prompt = self._prompt_for(handle, offer, proposing, note, round_n)
        future = asyncio.run_coroutine_threadsafe(
            self._fetch_prose(handle, prompt, round_n), self._loop
        )
        try:
            return future.result(timeout=self._turn_timeout_s + 5.0)
        except Exception:
            logger.warning("mediator got no reply from @%s (step %d)", handle, round_n)
            return ""

    def last_offer(self, handle: str) -> tuple[str, ...] | None:
        """The last outcome we actually read from *handle*, if any."""
        return self._last_offer.get(handle)

    def set_last_offer(self, handle: str, outcome: tuple[str, ...]) -> None:
        self._last_offer[handle] = outcome

    def to_outcome(self, offer: dict[str, Any]) -> tuple[str, ...] | None:
        """Coerce an interpreted offer dict into a valid NEGMAS outcome tuple.

        The interpreter LLM is asked to use canonical option tokens, but often
        returns near-misses (``"30%"`` for ``"30"``, ``"Tech"`` for the issue
        key). ``snap_offer`` rescues those before we'd otherwise reject the whole
        move — a spurious reject is what cascades into timeouts and misreported
        agreements live. A value with no near-match still yields ``None`` (snap
        refuses to force it), so a genuinely out-of-grid offer is not fabricated.
        """
        snapped = snap_offer(offer, self._names, self._options)
        if snapped is None:
            return None
        return tuple(snapped[name] for name in self._names)

    def default_outcome(self) -> tuple[str, ...]:
        return tuple(self._options[name][0] for name in self._names)

    def record(self, line: str) -> None:
        self.history.append(line)

    @property
    def names(self) -> list[str]:
        return list(self._names)


class RemoteAgentNegotiator(SAONegotiator):
    """A NEGMAS SAO negotiator backed by a real agent's replies over SLIM.

    ``propose``/``respond`` mirror the proven spike's ``MediatedAgent`` — the only
    change is the source of the prose: a real worker agent instead of a simulated
    persona. NEGMAS calls these synchronously on the ``mech.run()`` thread.
    """

    def __init__(self, handle: str, negotiation: MediatedNegotiation, **kw: Any) -> None:
        super().__init__(name=handle, **kw)
        self.handle = handle
        self._neg = negotiation

    def propose(self, state: Any, dest: Any = None) -> tuple[str, ...] | None:
        prose = self._neg.agent_move(
            self.handle, state.current_offer, proposing=True, round_n=state.step
        )
        reading = self._neg.interpret(self.handle, prose, proposing=True)
        offer = reading.get("offer", {}) if isinstance(reading, dict) else {}
        read = self._neg.to_outcome(offer)
        if read is not None:
            # Faithful read of this agent's move — record and remember it.
            self._neg.set_last_offer(self.handle, read)
            self._neg.note_opening_offer(self.handle, offer)
            outcome = read
        else:
            # Unreadable move (silence, off-grid, garbage). Hold THIS agent's own
            # last line, never ``state.current_offer`` — adopting the number on the
            # table would fabricate a concession the agent never made (the phantom
            # convergence bug). With no prior line, fall to its opening stance.
            outcome = self._neg.last_offer(self.handle) or self._neg.default_outcome()
            logger.info(
                "mediator step %d: @%s unreadable → holding own line %s (not the table)",
                state.step,
                self.handle,
                outcome,
            )
        self._neg.record(f"step {state.step}: @{self.handle} proposed {outcome}")
        logger.info("mediator step %d: @%s PROPOSE %s", state.step, self.handle, outcome)
        return outcome

    def respond(self, state: Any, source: Any = None) -> ResponseType:
        prose = self._neg.agent_move(
            self.handle, state.current_offer, proposing=False, round_n=state.step
        )
        reading = self._neg.interpret(self.handle, prose, proposing=False)
        action = reading.get("action") if isinstance(reading, dict) else None
        resp = ResponseType.ACCEPT_OFFER if action == "accept" else ResponseType.REJECT_OFFER
        self._neg.record(f"step {state.step}: @{self.handle} {resp.name} on {state.current_offer}")
        logger.info(
            "mediator step %d: @%s %s on %s",
            state.step,
            self.handle,
            resp.name,
            state.current_offer,
        )
        return resp


def least_satisfied_order(
    order: list[str],
    id_to_handle: dict[str, str | None],
    opening_offers: dict[str, dict[str, str]],
    standing: dict[str, str] | None,
    issue_options: dict[str, list[str]],
) -> list[str]:
    """Reorder a step's negotiator ids so the least-satisfied agent acts first.

    Satisfaction is each agent's opening ask scored against the ``standing`` offer
    (the same ordinal-grid estimate the episode uses post-hoc). Pure and total: with
    no standing offer yet (round 0) or no captured opening offers it returns ``order``
    unchanged — the default round-robin. The sort is stable, so agents whose
    satisfaction can't be scored keep their round-robin position (treated as
    already-satisfied, i.e. not pulled forward).
    """
    if not standing or not opening_offers:
        return list(order)
    from app.services.l9_episode import estimate_satisfaction

    satisfaction = estimate_satisfaction(opening_offers, standing, issue_options)
    if not satisfaction:
        return list(order)
    return sorted(order, key=lambda nid: satisfaction.get(id_to_handle.get(nid) or "", 1.0))


class SatisfactionOrderedSAO(SAOMechanism):
    """SAO mechanism that addresses the least-satisfied agent next, not round-robin.

    NEGMAS decides each step's turn order in ``next_negotitor_ids`` (its spelling);
    we override it to sort by satisfaction with the current standing offer, so the
    aligner spends turns on the agent who actually needs to move rather than on one
    already content with the offer. Termination is untouched — NEGMAS still stops at
    unanimity regardless of who is asked in what order (the anti-theatre property).
    """

    def __init__(self, *args: Any, negotiation: MediatedNegotiation, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._neg = negotiation

    def _standing_offer(self) -> dict[str, str] | None:
        offer = self.state.current_offer
        if not offer:
            return None
        names = self._neg.names
        return {names[i]: str(offer[i]) for i in range(min(len(names), len(offer)))}

    def next_negotitor_ids(self) -> list[str]:
        return least_satisfied_order(
            super().next_negotitor_ids(),
            {n.id: getattr(n, "handle", None) for n in self.negotiators},
            self._neg.opening_offers,
            self._standing_offer(),
            self._neg.issue_options,
        )


def build_mechanism(
    issues: list[dict[str, Any]], handles: list[str], negotiation: MediatedNegotiation, *, cap: int
) -> SAOMechanism:
    """Assemble the SAO mechanism with one live negotiator per participant.

    The mechanism addresses the least-satisfied agent first each step; until
    a standing offer exists it is exactly NEGMAS's round-robin.
    """
    negmas_issues = [
        make_issue(values=[str(v) for v in issue["options"]], name=issue["name"])
        for issue in issues
    ]
    mech = SatisfactionOrderedSAO(issues=negmas_issues, n_steps=cap, negotiation=negotiation)
    for handle in handles:
        mech.add(RemoteAgentNegotiator(handle, negotiation))
    return mech


def agreement_assignments(mech: SAOMechanism, issue_names: list[str]) -> dict[str, str] | None:
    """The agreed ``issue = value`` map, or ``None`` if NEGMAS never agreed."""
    agreement = mech.agreement
    if agreement is None:
        return None
    return {name: str(value) for name, value in zip(issue_names, agreement, strict=False)}
