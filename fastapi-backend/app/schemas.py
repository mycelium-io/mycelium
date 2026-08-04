# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Minimal schemas for Mycelium's core models.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# ── Room ──────────────────────────────────────────────────────────────────────


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_public: bool = True
    mas_id: str | None = None
    workspace_id: str | None = None


class RoomRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_public: bool
    created_at: datetime
    is_persistent: bool = False
    mas_id: str | None = None
    workspace_id: str | None = None

    model_config = {"from_attributes": True}


# ── Message ───────────────────────────────────────────────────────────────────


class MessageType:
    ANNOUNCE = "announce"
    DIRECT = "direct"
    BROADCAST = "broadcast"
    DELEGATE = "delegate"
    # Typed structured event (#392): source_event / action / concern / ...
    EVENT = "event"
    # Coordination system messages (posted directly by coordination service, not via HTTP API)
    COORDINATION_JOIN = "coordination_join"
    COORDINATION_START = "coordination_start"
    COORDINATION_TICK = "coordination_tick"
    COORDINATION_CONSENSUS = "coordination_consensus"
    COORDINATION_RETRY = "coordination_retry"


# ── event primitive (#392) ────────────────────────────────────────────────────

# Kinds with documented semantics. The vocabulary is deliberately open —
# unknown kinds are accepted (stateless, durable unless a TTL is given) so new
# uses don't need a schema change; these names just get defaults applied.
EVENT_KIND_SOURCE_EVENT = "source_event"
STATEFUL_EVENT_KINDS = frozenset({"action", "concern"})

EventStatus = Literal["open", "in_progress", "resolved"]


class EventProvenanceRef(BaseModel):
    """A cited reference backing an event."""

    type: Literal["pr", "commit", "issue", "page", "message"]
    ref: str = Field(..., min_length=1, description="e.g. 'org/repo#48' or a message id")
    url: str | None = None


class EventMetadata(BaseModel):
    """Structured metadata for ``message_type="event"``.

    Retention (``ttl_seconds``) and statefulness (``status``) are independent
    attributes, not distinct message types — one primitive covers a transient
    source-activity feed and a durable status-bearing ledger.
    """

    kind: str = Field(..., min_length=1, description="Event kind (open vocabulary)")
    ttl_seconds: int | None = Field(
        None, gt=0, description="Retention cap for transient kinds; absent = durable"
    )
    status: EventStatus | None = Field(
        None, description="Ledger status for stateful kinds; null for stateless"
    )
    payload: dict = Field(default_factory=dict, description="Kind-specific structured data")
    provenance: list[EventProvenanceRef] = Field(default_factory=list)
    correlation_id: str | None = Field(
        None, description="Groups related events / links updates to their origin"
    )

    @model_validator(mode="after")
    def _apply_kind_defaults(self) -> "EventMetadata":
        # Stateful kinds open by default; the ledger needs a queryable status.
        if self.kind in STATEFUL_EVENT_KINDS and self.status is None:
            self.status = "open"
        # source_event is stateless by definition.
        if self.kind == EVENT_KIND_SOURCE_EVENT and self.status is not None:
            raise ValueError("source_event is stateless — status must be null")
        return self


class EventStatusUpdate(BaseModel):
    """Body for PATCH /rooms/{name}/messages/{id} — transition an event's status."""

    status: EventStatus


class MessageCreate(BaseModel):
    sender_handle: str = Field(..., description="Sender handle (e.g., 'alpha#a8f3')")
    recipient_handle: str | None = Field(
        None, description="Recipient handle for direct messages; omit for broadcast"
    )
    message_type: str = Field(
        ...,
        description="Type: announce, direct, broadcast, delegate, or event",
        pattern="^(announce|direct|broadcast|delegate|event)$",
    )
    content: str = Field(..., min_length=1)
    metadata: EventMetadata | None = Field(
        None, description='Structured event metadata; required when message_type="event"'
    )

    @model_validator(mode="after")
    def _metadata_matches_type(self) -> "MessageCreate":
        if self.message_type == MessageType.EVENT and self.metadata is None:
            raise ValueError('message_type "event" requires metadata with a kind')
        if self.message_type != MessageType.EVENT and self.metadata is not None:
            raise ValueError('metadata is only valid on message_type "event"')
        return self


class MessageRead(BaseModel):
    id: UUID
    # Polymorphic: exactly one of room_name / coordination_session_id is set.
    room_name: str | None = None
    coordination_session_id: UUID | None = None
    sender_handle: str
    recipient_handle: str | None = None
    message_type: str
    content: str
    metadata: dict | None = Field(None, validation_alias="event_metadata")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class MessageListResponse(BaseModel):
    messages: list[MessageRead]
    total: int


# ── Participant (agent in a coordination session) ────────────────────────────


class ContextFile(BaseModel):
    """An opt-in shared file injected into a coordination session.

    The agent (via the CLI) explicitly selected this file to share with the
    session. Content is visible to other participants on tick fan-out and
    counts as a deliberate room write — it flows to KXP/CFN like any other
    room artifact. Use ``sha256`` for audit/dedupe and ``path`` for display.
    """

    path: str = Field(..., description="Absolute or repo-relative path on the sender's machine")
    content: str = Field(..., description="File contents at join time")
    sha256: str = Field(..., description="hex sha256 of content for audit and dedupe")


class ParticipantCreate(BaseModel):
    agent_handle: str = Field(..., description="Agent handle joining the room")
    intent: str | None = Field(None, description="Agent's requirements/intent for coordination")
    context_files: list[ContextFile] | None = Field(
        None,
        description="Files explicitly shared into the session at join time. "
        "Visible to other participants and forwarded to KXP.",
    )


class ContextFileRead(BaseModel):
    path: str
    sha256: str
    # Content is also returned to participants reading their own session
    # roster — they need it to render shared context.
    content: str


class ParticipantRead(BaseModel):
    id: UUID
    coordination_session_id: UUID
    agent_handle: str
    intent: str | None = None
    joined_at: datetime
    last_seen: datetime | None = None
    context_files: list[ContextFileRead] | None = None

    model_config = {"from_attributes": True}


class ParticipantListResponse(BaseModel):
    participants: list[ParticipantRead]
    total: int


# ── CoordinationSession ──────────────────────────────────────────────────────


class CoordinationSessionRead(BaseModel):
    id: UUID
    parent_room_name: str
    short_id: str
    state: str
    created_at: datetime
    join_window_ends_at: datetime | None = None
    mas_id: str | None = None
    workspace_id: str | None = None
    display_name: str

    model_config = {"from_attributes": True}


# ── AuditEvent ────────────────────────────────────────────────────────────────

VALID_RESOURCE_TYPES = {
    "COGNITIVE_ENGINE",
    "POLICY_ENFORCER",
    "MEMORY_PROVIDER",
    "MAS",
    "MAS-AGENT",
    "WORKFLOW",
    "TASK",
}

VALID_AUDIT_TYPES = {
    "RESOURCE_CREATED",
    "RESOURCE_UPDATED",
    "RESOURCE_DELETED",
    "RESOURCE_PURGED",
    "RESOURCE_PRUNED",
    "KNOWLEDGE_INGESTION",
    "KNOWLEDGE_QUERY",
    "MEMORY_OPERATION",
}


class AuditEventCreate(BaseModel):
    operation_id: str | None = None
    resource_type: str
    resource_identifier: str
    audit_type: str
    audit_resource_identifier: str
    audit_information: dict | None = None
    audit_extra_information: str | None = None
    created_by: UUID
    last_modified_by: UUID


class AuditEventRead(BaseModel):
    id: UUID
    operation_id: str | None = None
    resource_type: str
    resource_identifier: str
    audit_type: str
    audit_resource_identifier: str
    audit_information: dict | None = None
    audit_extra_information: str | None = None
    created_by: UUID
    created_on: datetime
    last_modified_by: UUID
    last_modified_on: datetime

    model_config = {"from_attributes": True}


# ── Memory ───────────────────────────────────────────────────────────────────


class MemoryCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=512)
    value: dict | str = Field(..., description="Memory content (dict or string)")
    tags: list[str] | None = None
    content_text: str | None = Field(
        None, description="Text for embedding; auto-generated from value if omitted"
    )
    embed: bool = Field(True, description="Generate vector embedding for semantic search")
    created_by: str = Field(..., description="Agent handle creating this memory")
    base_version: int | None = Field(
        None,
        description=(
            "Optimistic-concurrency guard: the version this write is based on. "
            "When set and it doesn't match the current on-disk version, the write "
            "is rejected (409) with the current content. Omit for last-write-wins."
        ),
    )


class MemoryBatchCreate(BaseModel):
    items: list[MemoryCreate] = Field(..., min_length=1, max_length=100)


class MemoryRead(BaseModel):
    id: UUID
    room_name: str
    key: str
    value: dict | str
    content_text: str | None = None
    created_by: str
    updated_by: str | None = None
    version: int
    tags: list[str] | None = None
    created_at: datetime
    updated_at: datetime
    file_path: str | None = None

    model_config = {"from_attributes": True}


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=100)
    tags_filter: list[str] | None = None
    min_similarity: float = Field(0.0, ge=0.0, le=1.0)


class MemorySearchResult(BaseModel):
    memory: MemoryRead
    similarity: float


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]
    total: int


class SubscriptionCreate(BaseModel):
    key_pattern: str = Field(..., min_length=1, description="Glob pattern for keys to watch")
    subscriber: str = Field(..., description="Agent handle subscribing")


class SubscriptionRead(BaseModel):
    id: UUID
    room_name: str
    subscriber: str
    key_pattern: str
    created_at: datetime

    model_config = {"from_attributes": True}
