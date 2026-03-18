"""
negmas_sao.py — Local Pydantic v2 mirror of NegMAS SAO types
=============================================================
Replicates the SAO (Stacked Alternating Offers) data model from
**negmas 0.15.1.post1** as proper Pydantic v2 ``BaseModel`` classes.

Source classes and their locations in negmas 0.15.1.post1:

    ResponseType         negmas.gb.common.ResponseType          (IntEnum)
    ThreadState          negmas.gb.common.ThreadState           (@define attrs)
    MechanismState       negmas.common.MechanismState           (@define attrs)
    GBState              negmas.gb.common.GBState               (@define attrs)
    SAOState             negmas.sao.common.SAOState             (@define attrs)
    SAOResponse          negmas.sao.common.SAOResponse          (@define attrs)
    SAONMI               negmas.sao.common.SAONMI               (@define frozen attrs)

Inheritance chain (negmas → this module):
    MechanismState
    └── GBState
        └── SAOState

    MechanismAction
    └── SAOResponse

    NegotiatorMechanismInterface
    └── SAONMI

Design notes
------------
- ``Outcome`` is typed as ``dict[str, Any] | tuple | None``.  NegMAS uses the
  same union; dict is the most common form in practice.
- ``SAONMI`` omits the internal ``_mechanism`` back-reference and the two
  computed fields (``time_limit``, ``n_steps``) which are derived at runtime.
  All required NMI base fields are given sensible defaults so the model can be
  constructed from a plain dict / JSON snapshot.
- ``GBState.n_participating`` is a read-only ``@property`` (matches NegMAS).
- All field names match the NegMAS source exactly so you can roundtrip with
  ``attrs.asdict()`` ↔ ``model_validate()``.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer, field_validator

# ---------------------------------------------------------------------------
# Outcome type alias
# NegMAS: negmas.outcomes.Outcome = tuple | dict | Mapping | None  # noqa: ERA001
# ---------------------------------------------------------------------------
Outcome = dict[str, Any] | tuple | None


# ---------------------------------------------------------------------------
# ResponseType — mirrors negmas.gb.common.ResponseType
# ---------------------------------------------------------------------------


class ResponseType(IntEnum):
    """
    Possible responses to offers during a NegMAS negotiation round.

    NegMAS source: negmas.gb.common.ResponseType
    """

    ACCEPT_OFFER = 0
    REJECT_OFFER = 1
    END_NEGOTIATION = 2
    NO_RESPONSE = 3
    WAIT = 4
    LEAVE = 5
    """Leave the negotiation without necessarily ending it for other negotiators."""


# ---------------------------------------------------------------------------
# ThreadState — mirrors negmas.gb.common.ThreadState
# ---------------------------------------------------------------------------


class ThreadState(BaseModel):
    """
    Per-thread state in a GB (Generalized Bargaining) negotiation round.

    NegMAS source: negmas.gb.common.ThreadState
    """

    new_offer: Outcome | None = None
    new_data: dict[str, Any] | None = None
    new_responses: dict[str, ResponseType] = Field(default_factory=dict)
    accepted_offers: list[Outcome] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# MechanismState — mirrors negmas.common.MechanismState
# ---------------------------------------------------------------------------


class MechanismState(BaseModel):
    """
    Base state for all NegMAS negotiation mechanisms.

    NegMAS source: negmas.common.MechanismState
    """

    running: bool = False
    """Whether the mechanism is currently running."""

    waiting: bool = False
    """Whether the mechanism is waiting for a response."""

    started: bool = False
    """Whether the mechanism has been started."""

    step: int = 0
    """Current negotiation step (0-indexed)."""

    time: float = 0.0
    """Elapsed wall-clock time in seconds."""

    relative_time: float = 0.0
    """
    Normalised time in [0, 1].
    Computed as ``max(step / n_steps, time / time_limit)``.
    """

    broken: bool = False
    """Whether the negotiation ended with no agreement due to a break."""

    timedout: bool = False
    """Whether the negotiation ended because a time/step limit was reached."""

    agreement: Outcome | None = None
    """The final agreed outcome, or None if not yet reached."""

    results: Any = None
    """
    Extended results field (Outcome | OutcomeSpace | tuple[Outcome] | None).
    Typed as Any to avoid importing negmas.outcomes.OutcomeSpace.
    """

    n_negotiators: int = 0
    """Total number of negotiators registered with the mechanism."""

    has_error: bool = False
    """Whether an error occurred during the negotiation."""

    error_details: str = ""
    """Human-readable description of the error, if any."""

    erred_negotiator: str = ""
    """ID of the negotiator that caused the error."""

    erred_agent: str = ""
    """ID of the agent that caused the error."""


# ---------------------------------------------------------------------------
# GBState — mirrors negmas.gb.common.GBState
# ---------------------------------------------------------------------------


class GBState(MechanismState):
    """
    State for Generalized Bargaining mechanisms.
    Parent class of SAOState.

    NegMAS source: negmas.gb.common.GBState
    """

    threads: dict[str, ThreadState] = Field(default_factory=dict)
    """Per-thread state keyed by thread/negotiator ID."""

    last_thread: str = ""
    """ID of the last thread that took an action."""

    left_negotiators: set[str] = Field(default_factory=set)
    """Set of negotiator IDs that left via a LEAVE response."""

    @computed_field  # type: ignore[misc]
    @property
    def n_participating(self) -> int:
        """Number of negotiators still active (= n_negotiators - left)."""
        return self.n_negotiators - len(self.left_negotiators)


# ---------------------------------------------------------------------------
# SAOState — mirrors negmas.sao.common.SAOState
# ---------------------------------------------------------------------------


class SAOState(GBState):
    """
    Full mechanism state for the Stacked Alternating Offers (SAO) protocol.

    NegMAS source: negmas.sao.common.SAOState
    Fields are declared in addition to those inherited from GBState / MechanismState.
    """

    current_offer: Outcome | None = None
    """The most recent offer on the table."""

    current_proposer: str | None = None
    """Negotiator ID of the agent who made the current offer."""

    current_proposer_agent: str | None = None
    """Agent ID corresponding to current_proposer (may differ in multi-agent settings)."""

    n_acceptances: int = 0
    """Number of negotiators who have accepted the current offer."""

    new_offers: list[tuple[str, Outcome | None]] = Field(default_factory=list)
    """List of (negotiator_id, offer) tuples produced in the current step."""

    new_offerer_agents: list[str | None] = Field(default_factory=list)
    """Agent IDs corresponding to new_offers entries."""

    last_negotiator: str | None = None
    """ID of the negotiator who last acted."""

    current_data: dict[str, Any] | None = None
    """Side-channel data (e.g. LLM rationale) attached to the current offer."""

    new_data: list[tuple[str, dict[str, Any] | None]] = Field(default_factory=list)
    """Side-channel data entries produced in the current step."""


# ---------------------------------------------------------------------------
# SAOResponse — mirrors negmas.sao.common.SAOResponse
# ---------------------------------------------------------------------------


class SAOResponse(BaseModel):
    """
    A single negotiator response in one SAO round.
    Encapsulates the decision (accept / reject / end / …) plus an optional offer.

    NegMAS source: negmas.sao.common.SAOResponse
    """

    response: ResponseType = ResponseType.NO_RESPONSE
    """The response decision."""

    outcome: Outcome | None = None
    """The proposed counter-offer, or None when not proposing."""

    data: dict[str, Any] | None = None
    """Optional side-channel metadata (e.g. LLM-generated rationale text)."""

    @field_validator("response", mode="before")
    @classmethod
    def _coerce_response(cls, v: Any) -> ResponseType:  # noqa: ANN401
        """Accept both the integer value (e.g. 0) and the enum name (e.g. 'ACCEPT_OFFER')."""
        if isinstance(v, ResponseType):
            return v
        if isinstance(v, int):
            return ResponseType(v)
        if isinstance(v, str):
            try:
                return ResponseType[v]  # name lookup: 'ACCEPT_OFFER' → ResponseType.ACCEPT_OFFER
            except KeyError:
                return ResponseType(int(v))  # numeric string fallback
        return ResponseType(v)

    @field_serializer("response")
    def _serialize_response(self, v: ResponseType) -> str:
        """Serialize ResponseType as its human-readable name instead of the integer value."""
        return v.name


# ---------------------------------------------------------------------------
# SAONMI — mirrors negmas.sao.common.SAONMI
# ---------------------------------------------------------------------------


class SAONMI(BaseModel):
    """
    NegotiatorMechanismInterface configuration snapshot for SAO.

    NegMAS source: negmas.sao.common.SAONMI (frozen attrs, inherits NegotiatorMechanismInterface)

    Omissions vs. the real SAONMI:
    - ``_mechanism`` back-reference (internal, not serialisable)
    - ``time_limit`` and ``n_steps`` computed fields (derive at runtime)

    All NegotiatorMechanismInterface base fields are present with defaults so
    this model can be built from a plain dict / JSON snapshot without needing
    a live mechanism object.
    """

    model_config = ConfigDict(frozen=True)

    # ── NegotiatorMechanismInterface base fields ─────────────────────────
    id: str = ""
    """Unique identifier for this NMI instance."""

    n_outcomes: int | float = 0
    """Total number of outcomes in the negotiation space."""

    shared_time_limit: float = float("inf")
    """Wall-clock time limit shared across all negotiators (seconds)."""

    shared_n_steps: int | None = None
    """Step limit shared across all negotiators. None = unlimited."""

    private_time_limit: float = float("inf")
    """Per-negotiator private time limit (seconds)."""

    private_n_steps: int | None = None
    """Per-negotiator private step limit. None = unlimited."""

    pend: float = 0.0
    """Probability of timeout per step. 0 = ignored."""

    pend_per_second: float = 0.0
    """Probability of timeout per second. 0 = ignored."""

    step_time_limit: float = float("inf")
    """Maximum time allowed for a single step (seconds)."""

    negotiator_time_limit: float = float("inf")
    """Maximum time allowed for a single negotiator per step (seconds)."""

    dynamic_entry: bool = False
    """Whether negotiators can join after the mechanism has started."""

    max_n_negotiators: int | None = None
    """Maximum number of negotiators allowed. None = unlimited."""

    annotation: dict[str, Any] = Field(default_factory=dict)
    """Free-form key-value annotations."""

    # ── SAO-specific flags ───────────────────────────────────────────────
    end_on_no_response: bool = True
    """End the negotiation if any agent responds with NO_RESPONSE."""

    one_offer_per_step: bool = False
    """If True, each step contains exactly one offer from one negotiator."""

    offering_is_accepting: bool = True
    """
    If True, making an offer counts as accepting it — the offerer does not
    need to explicitly accept their own offer again to reach agreement.
    """

    allow_none_with_data: bool = True
    """
    If True, a negotiator may offer None with associated data (e.g. text)
    without breaking the negotiation.
    """

    allow_negotiators_to_leave: bool = True
    """
    If True, negotiators may exit via LEAVE without forcing the whole
    negotiation to end for the remaining participants.
    """
