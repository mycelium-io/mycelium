"""
Lightweight SSTP (Semantic State Transfer Protocol) models for the CLI.

These models mirror the wire format used by Mycelium's coordination layer so
the CLI can validate outgoing agent replies and parse incoming coordination
ticks without importing the full backend package.

Agent reply shapes (agent → server, plain JSON in room message content):

    # Reply to a "propose" tick
    { "offer": { "budget": "medium", "timeline": "standard" } }

    # Reply to a "respond" tick
    { "action": "accept" }   # or "reject" or "end"

Inbound tick shape (server → agent, coordination_tick message content):
The content field is a JSON-serialised SSTPNegotiateMessage envelope whose
``payload`` carries the negotiation action details (see NegotiatePayload).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProposeReply(BaseModel):
    """Agent → Server reply to a 'propose' coordination tick.

    The CLI builds this from KEY=VALUE pairs and sends it as the room message
    content.  Pydantic validation ensures the shape is correct before posting.
    """

    offer: dict[str, str] = Field(..., min_length=1)


class RespondReply(BaseModel):
    """Agent → Server reply to a 'respond' coordination tick."""

    action: Literal["accept", "reject", "end"]


class NegotiatePayload(BaseModel):
    """Payload extracted from an inbound SSTPNegotiateMessage coordination_tick.

    Maps to the ``payload`` field of the SSTP envelope sent by RoomNegotiator.
    """

    kind: str = "negotiate"
    action: Literal["propose", "respond"]
    session_id: str
    participant_id: str
    round: int
    issue_options: dict[str, list[str]] = Field(default_factory=dict)
    current_offer: dict[str, str] | None = None
    proposer_id: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    n_steps: int | None = None


class InboundTick(BaseModel):
    """Minimal SSTP envelope shape for parsing inbound coordination_tick content.

    The full backend envelope has many more fields (origin, policy_labels, etc.).
    The CLI only needs ``kind`` and ``payload`` for display and reply validation.
    """

    kind: str = "negotiate"
    payload: NegotiatePayload
