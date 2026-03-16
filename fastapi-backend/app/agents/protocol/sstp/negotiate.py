"""sstp/negotiate.py — SSTPNegotiateMessage kind with NegMAS SAO semantic context."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ._base import EncodingType, _STBaseMessage
from .negmas_sao import SAONMI, SAOResponse, SAOState


class NegotiateSemanticContext(BaseModel):
    """
    SAO-specific semantic context for ``kind='negotiate'`` messages.

    Carries a full NegMAS SAO negotiation snapshot so that receivers have
    complete mechanism state, the latest response, and optionally the NMI
    configuration — all in one well-typed envelope.
    """

    schema_id: str = "urn:ioc:schema:negotiate:negmas-sao:v1"
    """Canonical schema URN identifying this as a NegMAS SAO negotiate context."""

    schema_version: str = "1.0"
    """Schema version."""

    encoding: EncodingType = "json"
    """Payload encoding (always json for NegMAS snapshots)."""

    session_id: str
    """Negotiation session / mechanism ID that this message belongs to."""

    sao_state: SAOState | None = None
    """Full SAO mechanism state snapshot at the time this message was created.

    ``None`` on initiate requests (no prior state exists yet).
    """

    sao_response: SAOResponse | None = None
    """The response produced by the sending negotiator in this round (if any)."""

    nmi: SAONMI | None = None
    """SAO NegotiatorMechanismInterface config snapshot (optional; omit if large)."""


class SSTPNegotiateMessage(_STBaseMessage):
    """
    A negotiation-round message backed by NegMAS SAO semantics.

    Unlike other kinds, ``semantic_context`` is typed as
    :class:`NegotiateSemanticContext` instead of the generic
    :class:`SemanticContext`, carrying a full SAO state snapshot,
    the sender's response, and an optional NMI configuration.
    """

    kind: Literal["negotiate"]

    # Override: narrow semantic_context to the SAO-specific subtype
    semantic_context: NegotiateSemanticContext  # type: ignore[override]
