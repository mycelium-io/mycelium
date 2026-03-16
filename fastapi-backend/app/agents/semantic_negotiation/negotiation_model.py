"""Negotiation model — component 3 of the semantic negotiation pipeline.

Takes issues (from component 1) and options per issue (from component 2) and
runs a multi-issue bilateral or multilateral negotiation using the NegMAS SAO
(Stacked Alternating Offers) mechanism.

All participants are represented by RoomNegotiator — decisions are routed
through Mycelium room messages rather than HTTP callbacks.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from negmas import SAOMechanism, make_issue
from negmas.preferences import LinearAdditiveUtilityFunction as UFun
import negmas.sao.negotiators as _sao_negotiators

from .room_negotiator import RoomNegotiator

logger = logging.getLogger(__name__)

_STRATEGY_MODULES = [
    "negmas.sao.negotiators",
    "negmas.sao.negotiators.controlled",
    "negmas.sao.negotiators.limited",
    "negmas.sao.negotiators.timebased",
]

_DEFAULT_STRATEGY = "BoulwareTBNegotiator"


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
    raise ValueError(f"Unknown negotiator strategy '{name}'. Available: {available}")


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
    preferences: Dict[str, Dict[str, float]] = field(default_factory=dict)
    issue_weights: Optional[Dict[str, float]] = None


@dataclass
class NegotiationOutcome:
    """Agreed value for a single issue."""

    issue_id: str
    chosen_option: str


@dataclass
class NegotiationResult:
    """Full result returned by :class:`NegotiationModel.run`.

    Attributes:
        agreement: Agreed outcomes per issue, or ``None`` if no agreement was reached.
        timedout: Whether the negotiation exhausted the step budget without agreement.
        broken: Whether a participant explicitly ended the negotiation.
        steps: Number of SAO rounds executed.
        history: Raw NegMAS extended trace as ``(step, negotiator_id, offer)`` tuples.
        raw_state: The final SAOState for advanced inspection.
    """

    agreement: Optional[List[NegotiationOutcome]]
    timedout: bool
    broken: bool
    steps: int
    history: List[Tuple[int, str, Any]] = field(default_factory=list)
    raw_state: Any = field(default=None, repr=False)


class NegotiationModel:
    """Runs a multi-issue SAO negotiation via NegMAS.

    All participants are driven by :class:`~.room_negotiator.RoomNegotiator` which
    routes every propose/respond decision through Mycelium room messages.

    Args:
        n_steps: Maximum SAO rounds before timeout.
        strategy: NegMAS negotiator class name or class object. Defaults to
            the ``NEGOTIATOR_STRATEGY`` env var, then ``BoulwareTBNegotiator``.
    """

    def __init__(self, n_steps: int = 100, strategy: "str | type | None" = None) -> None:
        if n_steps <= 0:
            raise ValueError("n_steps must be positive")
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

    def run(
        self,
        issues: List[str],
        options_per_issue: Dict[str, List[str]],
        participants: List[NegotiationParticipant],
        room_name: str = "unknown",
        loop: Optional[asyncio.AbstractEventLoop] = None,
        post_message_coro: Optional[Callable] = None,
        reply_timeout: float = 60.0,
        session_id: str = "unknown",
        registry: Optional[Dict[str, "RoomNegotiator"]] = None,
    ) -> NegotiationResult:
        """Run a full SAO negotiation session and return the result.

        Each participant is wired to a :class:`~.room_negotiator.RoomNegotiator` that
        posts coordination_tick messages to the room and awaits the agent's reply.

        Args:
            issues: Ordered list of issue identifiers.
            options_per_issue: Mapping from each issue id to its candidate options.
            participants: The negotiating parties (at least two required).
            room_name: Mycelium room name used for the message handshake.
            loop: The asyncio event loop for the room message bridge.
            post_message_coro: Async callable for posting room messages.
            reply_timeout: Seconds to wait for each agent reply per round.
            session_id: Alias for room_name when called from the pipeline.

        Returns:
            A :class:`NegotiationResult`.
        """
        self._validate_inputs(issues, options_per_issue, participants)

        effective_room = room_name if room_name != "unknown" else session_id
        effective_loop = loop or asyncio.get_event_loop()

        negmas_issues = self._build_issues(issues, options_per_issue)
        mechanism = SAOMechanism(issues=negmas_issues, n_steps=self.n_steps)

        # Registry of negotiators keyed by participant_id so coordination.py
        # can call negotiator.on_agent_reply(content) when the agent responds.
        # Also populate the caller-supplied *registry* dict (if any) so it is
        # accessible from the pipeline object BEFORE mechanism.run() blocks.
        self.negotiator_registry: Dict[str, RoomNegotiator] = {}

        for participant in participants:
            if post_message_coro is not None:
                neg = RoomNegotiator(
                    name=participant.name,
                    participant_id=participant.id,
                    room_name=effective_room,
                    loop=effective_loop,
                    post_message_coro=post_message_coro,
                    reply_timeout=reply_timeout,
                )
                self.negotiator_registry[participant.id] = neg
                if registry is not None:
                    registry[participant.id] = neg
                mechanism.add(neg)
            else:
                # Fallback: use built-in strategy with server-side utility function
                # (for unit tests or when no room bridge is configured).
                ufun = self._build_ufun(participant, issues, options_per_issue, mechanism)
                mechanism.add(self._negotiator_cls(name=participant.name), ufun=ufun)

        state = mechanism.run()
        return self._build_result(state, issues, mechanism)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_inputs(
        self,
        issues: List[str],
        options_per_issue: Dict[str, List[str]],
        participants: List[NegotiationParticipant],
    ) -> None:
        if len(participants) < 2:
            raise ValueError("At least two participants are required for a negotiation")
        for issue_id in issues:
            if issue_id not in options_per_issue:
                raise ValueError(f"Issue '{issue_id}' has no entry in options_per_issue")
            if not options_per_issue[issue_id]:
                raise ValueError(f"Issue '{issue_id}' has an empty options list")

    def _build_issues(self, issues: List[str], options_per_issue: Dict[str, List[str]]):
        return [make_issue(values=options_per_issue[issue_id], name=issue_id) for issue_id in issues]

    def _build_ufun(
        self,
        participant: NegotiationParticipant,
        issues: List[str],
        options_per_issue: Dict[str, List[str]],
        mechanism: SAOMechanism,
    ) -> UFun:
        values: Dict[str, Dict[str, float]] = {}
        for issue_id in issues:
            issue_prefs = participant.preferences.get(issue_id, {})
            values[issue_id] = {opt: float(issue_prefs.get(opt, 0.0)) for opt in options_per_issue[issue_id]}

        n_issues = len(issues)
        weights: Dict[str, float] = {
            issue_id: (
                float(participant.issue_weights[issue_id])
                if participant.issue_weights and issue_id in participant.issue_weights
                else 1.0 / n_issues
            )
            for issue_id in issues
        }

        return UFun(values=values, weights=weights, outcome_space=mechanism.outcome_space).normalize()

    def _build_result(
        self,
        state: Any,
        issues: List[str],
        mechanism: SAOMechanism,
    ) -> NegotiationResult:
        agreement: Optional[List[NegotiationOutcome]] = None
        if state.agreement is not None:
            agreement = [
                NegotiationOutcome(issue_id=issue_id, chosen_option=str(state.agreement[idx]))
                for idx, issue_id in enumerate(issues)
            ]

        return NegotiationResult(
            agreement=agreement,
            timedout=state.timedout,
            broken=state.broken,
            steps=state.step,
            history=list(mechanism.extended_trace),
            raw_state=state,
        )
