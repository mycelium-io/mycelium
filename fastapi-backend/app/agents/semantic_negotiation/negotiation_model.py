"""Negotiation model — component 3 of the semantic negotiation pipeline.

Takes issues (from component 1) and options per issue (from component 2) and
runs a multi-issue bilateral or multilateral negotiation using the NegMAS SAO
(Stacked Alternating Offers) mechanism.

All participants are represented by RoomNegotiator — decisions are routed
through Mycelium room messages rather than HTTP callbacks.

Ported from ioc-cfn-cognitive-agents/semantic-negotiation-agent/app/agent/negotiation_model.py.
Added: CounterOfferResult, counter_offer(), per-session concurrency guard, round_decisions.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import negmas.sao.negotiators as _sao_negotiators
from negmas import SAOMechanism, make_issue
from negmas.preferences import LinearAdditiveUtilityFunction as UFun

from .room_negotiator import RoomNegotiator

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_STRATEGY_MODULES = [
    "negmas.sao.negotiators",
    "negmas.sao.negotiators.controlled",
    "negmas.sao.negotiators.limited",
    "negmas.sao.negotiators.timebased",
]

_DEFAULT_STRATEGY = "BoulwareTBNegotiator"

# ---------------------------------------------------------------------------
# Per-session concurrency guard
# ---------------------------------------------------------------------------
# Prevents two concurrent requests with the same session_id from colliding
# on _DECISIONS keys or SAOMechanism state.

_ACTIVE_SESSIONS: dict[str, str] = {}
_ACTIVE_SESSIONS_LOCK = threading.Lock()


def _resolve_strategy(name: str) -> type:
    """Resolve a NegMAS negotiator class by name."""
    cls = getattr(_sao_negotiators, name, None)
    if cls is not None:
        return cls
    for mod_path in _STRATEGY_MODULES:
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, name, None)
            if cls is not None:
                return cls
        except ImportError:
            continue
    available = sorted(n for n in dir(_sao_negotiators) if "Negotiator" in n or "Agent" in n)
    msg = f"Unknown negotiator strategy '{name}'. Available: {available}"
    raise ValueError(msg)


@dataclass
class NegotiationParticipant:
    """Represents one participant (agent) in a negotiation session.

    Attributes:
        id: Unique identifier — matches Session.agent_handle.
        name: Human-readable display name.
        preferences: Per-issue option utilities ``{issue_id: {option_label: utility}}``.
            Utilities should be in [0.0, 1.0].
        issue_weights: Optional per-issue importance weights for the linear additive
            utility function. Defaults to equal weights when omitted.
    """

    id: str
    name: str
    preferences: dict[str, dict[str, float]] = field(default_factory=dict)
    issue_weights: dict[str, float] | None = None


@dataclass
class NegotiationOutcome:
    """Agreed value for a single issue."""

    issue_id: str
    chosen_option: str


@dataclass
class NegotiationResult:
    """Full result returned by :class:`NegotiationModel.run`.

    Attributes:
        agreement: Agreed outcomes per issue, or None if no agreement.
        timedout: Whether the negotiation exhausted the step budget.
        broken: Whether a participant explicitly ended the negotiation.
        steps: Number of SAO rounds executed.
        history: Raw NegMAS extended trace as (step, negotiator_id, offer) tuples.
        round_decisions: Per-round agent decisions keyed by 1-based round number.
            Each value is a list of {participant_id, action, offer?} dicts.
        raw_state: The final SAOState for advanced inspection.
    """

    agreement: list[NegotiationOutcome] | None
    timedout: bool
    broken: bool
    steps: int
    history: list[tuple[int, str, Any]] = field(default_factory=list)
    round_decisions: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    raw_state: Any = field(default=None, repr=False)


@dataclass
class CounterOfferResult:
    """Result of :func:`counter_offer`.

    Attributes:
        counter_offer_valid: True when the agent owned the next proposer slot
            and the offer was valid.
        rejection_reason: One of 'invalid_round', 'wrong_turn', 'explicit_reject',
            'missing_offer', or 'incomplete_offer'.
        expected_proposer_id: Populated only on rejection_reason='wrong_turn'.
        accepted_offer: Present when action='accept'. Shape: {issue_id: chosen_option}.
        new_offer: Present when a valid counter-offer is accepted.
        error_detail: Arbitrary dict forwarded to the HTTP error body.
    """

    counter_offer_valid: bool
    rejection_reason: str | None = None
    expected_proposer_id: str | None = None
    accepted_offer: dict[str, str] | None = None
    new_offer: dict[str, str] | None = None
    error_detail: dict[str, Any] | None = None


def counter_offer(  # noqa: PLR0911, PLR0913
    *,
    action: str,
    round_num: int,
    agent_id: str,
    offer_dict: dict[str, str] | None,
    trace_rounds: list[dict[str, Any]],
    issues: list[str],
    participant_ids: list[str],
    session_id: str = "unknown",
) -> CounterOfferResult:
    """Evaluate an agent's accept / reject / counter-offer decision.

    Pure domain logic — no NegMAS run is triggered. When the agent supplies
    a valid counter-offer it is returned as CounterOfferResult.new_offer for
    the route to append to the running trace.

    Turn ownership: each round rotates the proposer slot round-robin among
    participants. Offers submitted out-of-turn are silently discarded.
    """
    total_rounds = len(trace_rounds)

    if round_num < 1 or round_num > total_rounds:
        return CounterOfferResult(
            counter_offer_valid=False,
            rejection_reason="invalid_round",
            error_detail={"round": round_num, "total_rounds": total_rounds},
        )

    if action == "accept":
        return CounterOfferResult(
            counter_offer_valid=True,
            accepted_offer=dict(trace_rounds[round_num - 1]["offer"]),
        )

    if action == "reject":
        return CounterOfferResult(
            counter_offer_valid=True,
            rejection_reason="explicit_reject",
        )

    # counter_offer — enforce turn ownership
    current_proposer_id: str = trace_rounds[round_num - 1]["proposer_id"]

    if round_num < total_rounds:
        expected_next_proposer_id: str = trace_rounds[round_num]["proposer_id"]
    else:
        candidates = [pid for pid in participant_ids if pid != current_proposer_id]
        expected_next_proposer_id = candidates[0] if candidates else current_proposer_id

    logger.info(
        "[%s] counter-offer — agent=%s expected=%s round=%d",
        session_id,
        agent_id,
        expected_next_proposer_id,
        round_num,
    )

    if agent_id != expected_next_proposer_id:
        logger.warning(
            "[%s] counter-offer REJECTED — '%s' offered out-of-turn (expected '%s').",
            session_id,
            agent_id,
            expected_next_proposer_id,
        )
        return CounterOfferResult(
            counter_offer_valid=False,
            rejection_reason="wrong_turn",
            expected_proposer_id=expected_next_proposer_id,
        )

    if not offer_dict or not isinstance(offer_dict, dict):
        return CounterOfferResult(
            counter_offer_valid=False,
            rejection_reason="missing_offer",
            error_detail={"detail": "action='counter_offer' requires 'offer' key"},
        )

    missing_issues = [i for i in issues if i not in offer_dict]
    if missing_issues:
        return CounterOfferResult(
            counter_offer_valid=False,
            rejection_reason="incomplete_offer",
            error_detail={"missing_issues": missing_issues},
        )

    logger.info(
        "[%s] Counter-offer VALID — agent '%s' proposes %s", session_id, agent_id, offer_dict
    )
    return CounterOfferResult(counter_offer_valid=True, new_offer=dict(offer_dict))


class NegotiationModel:
    """Runs a multi-issue SAO negotiation via NegMAS.

    All participants are driven by RoomNegotiator which routes every
    propose/respond decision through Mycelium room messages.

    Args:
        n_steps: Maximum SAO rounds before timeout.
        strategy: NegMAS negotiator class name or class object. Defaults to
            the NEGOTIATOR_STRATEGY env var, then BoulwareTBNegotiator.
    """

    def __init__(self, n_steps: int = 100, strategy: str | type | None = None) -> None:
        import os

        if n_steps <= 0:
            msg = "n_steps must be positive"
            raise ValueError(msg)
        self.n_steps = n_steps

        if strategy is None:
            strategy = os.environ.get("NEGOTIATOR_STRATEGY", _DEFAULT_STRATEGY)

        if isinstance(strategy, str):
            self._negotiator_cls = _resolve_strategy(strategy)
        else:
            self._negotiator_cls = strategy

        logger.info("NegotiationModel — strategy: %s", self._negotiator_cls.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(  # noqa: PLR0913
        self,
        issues: list[str],
        options_per_issue: dict[str, list[str]],
        participants: list[NegotiationParticipant],
        room_name: str = "unknown",
        loop: asyncio.AbstractEventLoop | None = None,
        post_message_coro: Callable | None = None,
        reply_timeout: float = 60.0,
        session_id: str = "unknown",
        registry: dict[str, RoomNegotiator] | None = None,
    ) -> NegotiationResult:
        """Run a full SAO negotiation session and return the result."""
        self._validate_inputs(issues, options_per_issue, participants)

        effective_room = room_name if room_name != "unknown" else session_id

        with _ACTIVE_SESSIONS_LOCK:
            if effective_room in _ACTIVE_SESSIONS:
                owner = _ACTIVE_SESSIONS[effective_room]
                msg = (
                    f"Session '{effective_room}' is already running in thread '{owner}'. "
                    "Concurrent negotiations must use unique session IDs."
                )
                raise ValueError(msg)
            _ACTIVE_SESSIONS[effective_room] = threading.current_thread().name
        logger.debug(
            "[%s] session acquired (thread=%s)", effective_room, threading.current_thread().name
        )

        try:
            return self._run_negotiation(
                issues,
                options_per_issue,
                participants,
                effective_room,
                loop,
                post_message_coro,
                reply_timeout,
                registry,
            )
        finally:
            with _ACTIVE_SESSIONS_LOCK:
                _ACTIVE_SESSIONS.pop(effective_room, None)
            logger.debug("[%s] session released", effective_room)

    def counter_offer(  # noqa: PLR0913
        self,
        *,
        action: str,
        round_num: int,
        agent_id: str,
        offer_dict: dict[str, str] | None,
        trace_rounds: list[dict[str, Any]],
        issues: list[str],
        participant_ids: list[str],
        session_id: str = "unknown",
    ) -> CounterOfferResult:
        """Delegate to module-level counter_offer function."""
        return counter_offer(
            action=action,
            round_num=round_num,
            agent_id=agent_id,
            offer_dict=offer_dict,
            trace_rounds=trace_rounds,
            issues=issues,
            participant_ids=participant_ids,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_negotiation(  # noqa: PLR0913
        self,
        issues: list[str],
        options_per_issue: dict[str, list[str]],
        participants: list[NegotiationParticipant],
        room_name: str,
        loop: asyncio.AbstractEventLoop | None,
        post_message_coro: Callable | None,
        reply_timeout: float,
        registry: dict[str, RoomNegotiator] | None,
    ) -> NegotiationResult:
        effective_loop = loop or asyncio.get_event_loop()

        negmas_issues = self._build_issues(issues, options_per_issue)
        mechanism = SAOMechanism(issues=negmas_issues, n_steps=self.n_steps)

        self.negotiator_registry: dict[str, RoomNegotiator] = {}

        for participant in participants:
            if post_message_coro is not None:
                neg = RoomNegotiator(
                    name=participant.name,
                    participant_id=participant.id,
                    room_name=room_name,
                    loop=effective_loop,
                    post_message_coro=post_message_coro,
                    reply_timeout=reply_timeout,
                )
                self.negotiator_registry[participant.id] = neg
                if registry is not None:
                    registry[participant.id] = neg
                mechanism.add(neg)
            else:
                # Fallback: server-side utility function (unit tests / no room bridge)
                ufun = self._build_ufun(participant, issues, options_per_issue, mechanism)
                mechanism.add(self._negotiator_cls(name=participant.name), ufun=ufun)

        state = mechanism.run()
        return self._build_result(state, issues, mechanism)

    def _validate_inputs(
        self,
        issues: list[str],
        options_per_issue: dict[str, list[str]],
        participants: list[NegotiationParticipant],
    ) -> None:
        if len(participants) < 2:  # noqa: PLR2004
            msg = "At least two participants are required for a negotiation"
            raise ValueError(msg)
        for issue_id in issues:
            if issue_id not in options_per_issue:
                msg = f"Issue '{issue_id}' has no entry in options_per_issue"
                raise ValueError(msg)
            if not options_per_issue[issue_id]:
                msg = f"Issue '{issue_id}' has an empty options list"
                raise ValueError(msg)

    def _build_issues(self, issues: list[str], options_per_issue: dict[str, list[str]]) -> list:
        return [
            make_issue(values=options_per_issue[issue_id], name=issue_id) for issue_id in issues
        ]

    def _build_ufun(
        self,
        participant: NegotiationParticipant,
        issues: list[str],
        options_per_issue: dict[str, list[str]],
        mechanism: SAOMechanism,
    ) -> UFun:
        values: dict[str, dict[str, float]] = {}
        for issue_id in issues:
            issue_prefs = participant.preferences.get(issue_id, {})
            values[issue_id] = {
                opt: float(issue_prefs.get(opt, 0.0)) for opt in options_per_issue[issue_id]
            }
        n_issues = len(issues)
        weights: dict[str, float] = {
            issue_id: (
                float(participant.issue_weights[issue_id])
                if participant.issue_weights and issue_id in participant.issue_weights
                else 1.0 / n_issues
            )
            for issue_id in issues
        }
        return UFun(
            values=values, weights=weights, outcome_space=mechanism.outcome_space
        ).normalize()

    def _build_result(
        self,
        state: Any,  # noqa: ANN401
        issues: list[str],
        mechanism: SAOMechanism,
    ) -> NegotiationResult:
        agreement: list[NegotiationOutcome] | None = None
        if state.agreement is not None:
            agreement = [
                NegotiationOutcome(issue_id=issue_id, chosen_option=str(state.agreement[idx]))
                for idx, issue_id in enumerate(issues)
            ]

        # Build round_decisions from extended trace
        round_decisions: dict[int, list[dict[str, Any]]] = {}
        for step, negotiator_id, offer in mechanism.extended_trace:
            rnd = step + 1
            round_decisions.setdefault(rnd, []).append(
                {
                    "participant_id": str(negotiator_id),
                    "offer": {issues[i]: str(v) for i, v in enumerate(offer)}
                    if offer is not None
                    else None,
                }
            )

        return NegotiationResult(
            agreement=agreement,
            timedout=state.timedout,
            broken=state.broken,
            steps=state.step,
            history=list(mechanism.extended_trace),
            round_decisions=round_decisions,
            raw_state=state,
        )
