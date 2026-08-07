# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The SAO mediator — the aligner as a *driver* of a real negotiation.

The aligner as a passive **observer** only wakes to grade a finished transcript,
so agents that had already agreed by message 5 kept re-agreeing for seven more
turns because nothing *ran* the negotiation and said "you agreed — stop." This
module fixes that by actively driving the negotiation.

An LLM mediator reads natural-language agent
chatter, maps it onto a NEGMAS **Stacked Alternating Offers** mechanism, and
**NEGMAS owns termination** — the mechanism stops the instant everyone accepts
the standing offer. Convergence needs **memory + a brokering mediator + BATNA**
(the "camp counselor"); bare-offer relaying to stateless agents deadlocks. This
module runs that loop *live over SLIM*
against real worker agents, still driven by the reserved ``@aligner`` handle.

**The Node/Python-free seam.** NEGMAS is a synchronous Python mechanism; SLIM I/O
is async on the backend event loop. Rather than know NEGMAS's next-actor and
inject externally-collected moves (version-fragile), we run ``mech.run()`` on a
worker thread and let each negotiator block for its own agent's real reply: the
negotiator's ``propose``/``respond`` bridge back to the loop with
``run_coroutine_threadsafe`` to publish an ``@``-addressed prompt and collect the
reply the persister records, then interpret the prose in-thread. NEGMAS keeps
full ownership of proposer rotation and the unanimity stop; we only supply each
agent's move when NEGMAS asks for it. LLM calls (discover/broker/interpret) run
synchronously in-thread via ``litellm.completion`` — which also sidesteps the
Bedrock ``acompletion`` issue (see ``plan_compiler``).

The mediator is deliberately *interpretation over the agents' prose*: agents are
never required to emit structured markers (a future cleanup will retire the
``parse_position_marker`` hack entirely). The mediator restates its reading into
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

from app.config import settings
from app.services.offer_snap import snap_offer

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

# Bounded LLM turns keep interpretation cheap and predictable.
_MAX_TOKENS = 500
_DISCOVER_TEMPERATURE = 0.0
_BROKER_TEMPERATURE = 0.3

# No-deal framing — the BATNA that turns a hardliner into a negotiator (the one
# thing the v1 spike lacked). Appended to every agent-facing prompt.
_BATNA = (
    "If the team reaches NO agreement there is NO change at all — the worst outcome for "
    "everyone, you included. A compromise you can live with beats no deal. Protect your one "
    "genuine hard line; concede everything secondary."
)


def _extract_json(text: str) -> dict[str, Any]:
    """First ``{...}`` JSON object in a model response (empty dict on miss)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def llm_sync(prompt: str, *, system: str = "", temperature: float = _BROKER_TEMPERATURE) -> str:
    """One blocking chat completion using the configured model.

    Synchronous on purpose: the mediator's LLM turns run inside NEGMAS's
    ``mech.run()`` worker thread, and ``litellm.completion`` also avoids the
    Bedrock ``acompletion`` breakage the plan compiler documents.
    """
    import litellm

    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "max_tokens": _MAX_TOKENS,
        "temperature": temperature,
        "messages": (
            ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}]
        ),
    }
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content or ""


def discover_issues(
    task: str, positions: dict[str, str], *, llm: Callable[..., str] | None = None
) -> list[dict[str, Any]]:
    """Mediator stage 1 — read opening prose into negotiable issues + options.

    Ported from the spike's ``discover_issues``. Returns a list of
    ``{"name": snake_case, "options": [token, ...]}``. An empty/degenerate result
    (fewer than one issue) is a signal to the caller to bail to a rejected
    verdict rather than build an empty mechanism.
    """
    llm = llm or llm_sync
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
        llm: Callable[..., str] | None = None,
        on_reading: Callable[[str, dict[str, Any], bool], None] | None = None,
    ) -> None:
        self._issues = issues
        self._names = [i["name"] for i in issues]
        self._options = {i["name"]: i["options"] for i in issues}
        self._cap = cap
        self._loop = loop
        self._fetch_prose = fetch_prose
        self._turn_timeout_s = turn_timeout_s
        self._llm = llm or llm_sync
        self._on_reading = on_reading
        self.history: list[str] = []

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
                "nudge the holdout toward closing — remind them a near-deal beats no change. Be "
                "concrete and fair, not preachy.",
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


class LiveNegotiator(SAONegotiator):
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
        outcome = self._neg.to_outcome(
            reading.get("offer", {}) if isinstance(reading, dict) else {}
        )
        outcome = outcome or state.current_offer or self._neg.default_outcome()
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


def build_mechanism(
    issues: list[dict[str, Any]], handles: list[str], negotiation: MediatedNegotiation, *, cap: int
) -> SAOMechanism:
    """Assemble the SAO mechanism with one live negotiator per participant."""
    negmas_issues = [
        make_issue(values=[str(v) for v in issue["options"]], name=issue["name"])
        for issue in issues
    ]
    mech = SAOMechanism(issues=negmas_issues, n_steps=cap)
    for handle in handles:
        mech.add(LiveNegotiator(handle, negotiation))
    return mech


def agreement_assignments(mech: SAOMechanism, issue_names: list[str]) -> dict[str, str] | None:
    """The agreed ``issue = value`` map, or ``None`` if NEGMAS never agreed."""
    agreement = mech.agreement
    if agreement is None:
        return None
    return {name: str(value) for name, value in zip(issue_names, agreement, strict=False)}
