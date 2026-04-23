# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
sstp/_base.py — Shared literals, sub-models, and envelope base for SSTP.

Imported by every kind module; do not import this directly from outside
the package — use ``from protocol.sstp import ...`` instead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literals / type aliases
# ---------------------------------------------------------------------------

ProtocolType = Literal["SSTP"]
SensitivityType = Literal["public", "internal", "restricted", "confidential"]
PropagationType = Literal["forward", "restricted", "no_forward"]
EncodingType = Literal["json", "structured_text", "hybrid"]
MergeStrategy = Literal["add", "replace", "merge", "crdt"]
PayloadRefType = Literal["inline", "external"]


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class Origin(BaseModel):
    """Who produced this message."""

    actor_id: str
    """ID of the agent, engine, or memory node that created the message."""

    tenant_id: str
    """Tenant / organisation identifier."""

    attestation: str | None = None
    """Optional credential or signature proving identity."""


class SemanticContext(BaseModel):
    """Schema and encoding metadata for the payload."""

    schema_id: str
    """Canonical schema URN (e.g. ``urn:ioc:schema:intent:v1``)."""

    schema_version: str
    """Version string of the schema."""

    encoding: EncodingType = "json"
    """How the payload is encoded."""


class PolicyLabels(BaseModel):
    """Data-handling policy annotations."""

    sensitivity: SensitivityType
    propagation: PropagationType
    retention_policy: str
    """Reference to a retention policy by ID."""


class Provenance(BaseModel):
    """Lineage of this message."""

    sources: list[str] = Field(default_factory=list)
    """Source references (URNs, message IDs, document refs)."""

    transforms: list[str] = Field(default_factory=list)
    """Transform / processing step references applied before this message."""


class PayloadRef(BaseModel):
    """A reference to where payload content is stored."""

    type: PayloadRefType
    ref: str
    """URI pointing at the actual payload content."""


class LogicalClock(BaseModel):
    """Lamport scalar or vector clock snapshot."""

    type: Literal["lamport", "vector"] = "lamport"
    value: int | dict[str, int] = 0
    """Scalar int for lamport; ``{actor_id: counter}`` dict for vector."""


# ---------------------------------------------------------------------------
# Common envelope base
# ---------------------------------------------------------------------------


class _STBaseMessage(BaseModel):
    """Internal base — do not use directly; import one of the kind models."""

    protocol: ProtocolType = "SSTP"
    version: str = "0"

    # -- required envelope -------------------------------------------------
    message_id: str
    """UUIDv4 or content-addressed hash identifying this message."""

    dt_created: str
    """ISO 8601 creation timestamp (e.g. ``2026-02-27T10:00:00Z``)."""

    origin: Origin
    semantic_context: SemanticContext
    payload_hash: str
    """SHA-256 hex digest of the serialised payload field."""

    policy_labels: PolicyLabels
    provenance: Provenance

    # -- payload (kind-specific, kept as open dict for flexibility) --------
    payload: dict[str, Any] = Field(default_factory=dict)

    # -- optional general fields -------------------------------------------
    state_object_id: str | None = None
    """URN or fabric address of the state object this message targets."""

    parent_ids: list[str] = Field(default_factory=list)
    """Message IDs this message is a reply to or derived from."""

    logical_clock: LogicalClock | None = None
    """Lamport or vector clock for ordering."""

    payload_refs: list[PayloadRef] = Field(default_factory=list)
    """External or split-payload references."""

    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    """Confidence in this message's content (0.0 - 1.0)."""

    ttl_seconds: int | None = None
    """Time-to-live in seconds. None = no expiry."""

    merge_strategy: MergeStrategy | None = None
    """How a receiving store should merge this message into shared state."""

    risk_score: float | None = None
    """Risk assessment score attached by the issuing policy engine."""
