# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Minimal schemas for Mycelium's core models.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# Two shape rules, deliberately distinct. A *handle* is an identity and can be
# minted by a real IdP, so it allows the `@` a corporate SSO `preferred_username`
# carries (e.g. `user@example.com`). A *slug* is a filename / composer trigger
# token (skill names) and stays clean. The CLI (`mycelium/protocol.py`) and the
# frontend (`acting-as-picker.tsx`) keep matching copies; the thin CLI can't
# import this package.
HANDLE_PATTERN = r"^[a-z0-9][a-z0-9._@-]*$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"

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
    #: When the room was last active (its transcript's mtime), or ``created_at``
    #: for a room with no messages yet. Populated by ``GET /rooms``.
    last_activity: datetime | None = None
    is_persistent: bool = False
    mas_id: str | None = None
    workspace_id: str | None = None

    model_config = {"from_attributes": True}


# ── Message ───────────────────────────────────────────────────────────────────


class MessageType(StrEnum):
    ANNOUNCE = "announce"
    DIRECT = "direct"
    BROADCAST = "broadcast"
    DELEGATE = "delegate"
    # Typed structured event: source_event / action / concern / ...
    EVENT = "event"
    # System messages, written server-side by the coordination and plan
    # services — never accepted over the HTTP API (see ApiMessageType).
    COORDINATION_JOIN = "coordination_join"
    COORDINATION_START = "coordination_start"
    COORDINATION_TICK = "coordination_tick"
    COORDINATION_CONSENSUS = "coordination_consensus"
    COORDINATION_RETRY = "coordination_retry"
    PLAN_UPDATED = "plan_updated"


# The message types a client may create over the HTTP API. The system-posted
# kinds above are written server-side and are not accepted on inbound requests.
ApiMessageType = Literal[
    MessageType.ANNOUNCE,
    MessageType.DIRECT,
    MessageType.BROADCAST,
    MessageType.DELEGATE,
    MessageType.EVENT,
]


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
    message_type: ApiMessageType = Field(
        ...,
        description="Type: announce, direct, broadcast, delegate, or event",
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
    episode: str | None = Field(
        None, description="L9 episode URN this message belongs to, if any (for grouping/folding)"
    )
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
    meta: dict[str, Any] | None = Field(
        None,
        description=(
            "Extra YAML frontmatter merged into the memory file — soft, typed, "
            "user-extensible data such as 'expandable: true' or "
            "'supersedes: decisions/db-v1'. Keys the store manages (key, version, "
            "timestamps, authorship, tags, value) are ignored here. Frontmatter "
            "already on disk is preserved across writes; this overlays it."
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
    expandable: bool = Field(
        False,
        description=(
            "Whether this memory opts in to transclusion via ``![[key]]``. "
            "Mirrors the ``expandable`` frontmatter flag."
        ),
    )
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


# ── Skills (global, reusable invokable skills) ────────────────────────────────
# Same grain as memory (markdown + frontmatter) but a distinct, project-level
# store — skills are reusable across rooms. See app/services/skills.py.


class SkillCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=SLUG_PATTERN,
        description="Skill slug (kebab-case); the filename and the composer's /trigger token",
    )
    description: str = Field("", max_length=512, description="One-line summary shown in listings")
    body: str = Field("", description="The skill's prose (SKILL.md-style instructions)")
    tags: list[str] | None = None
    created_by: str = Field(..., description="Handle creating this skill")
    meta: dict[str, Any] | None = Field(
        None,
        description=(
            "Extra YAML frontmatter merged into the skill file. Managed keys "
            "(name, description, version, timestamps, authorship, tags) are ignored."
        ),
    )


class SkillRead(BaseModel):
    name: str
    description: str = ""
    body: str = ""
    tags: list[str] | None = None
    created_by: str
    updated_by: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillListResponse(BaseModel):
    skills: list[SkillRead]
    total: int


# ── Principal (self-asserted user store) ──────────────────────────────────────
# The human made first-class, symmetric with agents/<handle>. An agent's owner
# points at a users/<handle>; a team groups these handles. Trust is self-asserted
# — the handle is consistent, not cryptographic.


class UserCreate(BaseModel):
    handle: str = Field(..., min_length=1, pattern=HANDLE_PATTERN)
    display_name: str = ""
    teams: list[str] = Field(default_factory=list)
    notify: str | None = None


class OwnedAgentRead(BaseModel):
    """One agent bound to a principal, with its room."""

    room: str
    handle: str
    adapter: str
    team: str | None = None


class UserRead(BaseModel):
    handle: str
    display_name: str = ""
    teams: list[str] = Field(default_factory=list)
    notify: str | None = None
    owns: list[OwnedAgentRead] = Field(default_factory=list)


class UserListResponse(BaseModel):
    users: list[UserRead]
    total: int


class TeamRead(BaseModel):
    """A team, rolled up from the agents fielded under it and its member users."""

    team: str
    members: list[str] = Field(default_factory=list)
    agent_count: int = 0


class TeamListResponse(BaseModel):
    teams: list[TeamRead]
    total: int


# ── Agent manifest ────────────────────────────────────────────────────────────


class AgentRead(BaseModel):
    """Structured view of an agent's manifest, as returned by GET /rooms/{room}/agents."""

    handle: str
    adapter: str
    kind: str | None = None
    description: str = ""
    cwd: str | None = None
    owner: str | None = None
    team: str | None = None
    allow_from: list[str] = Field(default_factory=list)
    # a2a adapter: the remote Agent Card locator, resolved endpoint, and the
    # skills it advertises. None/empty for every other adapter.
    a2a_card: str | None = None
    a2a_endpoint: str | None = None
    a2a_skills: list[str] = Field(default_factory=list)


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


# ── L9 episodes (protocol inspector) ─────────────────────────────────────────
#
# The episode read API projects persisted L9 episode records into JSON the UI
# inspector renders. These models are the typed seam: the backend routes declare
# them as `response_model`, so FastAPI validates + filters the raw parsed dicts
# into exactly this shape. They mirror the frontend `L9Envelope` / `EpisodeDetail`
# TypeScript interfaces 1:1, so neither side can silently read a field the other
# doesn't send. Fields are permissive (most optional) because these records are
# historical markdown files, not freshly minted objects — a single odd envelope
# must not 500 the whole inspector. The one invariant: every envelope has a kind.


class L9ActorRead(BaseModel):
    id: str
    role: str


class L9ParticipantsRead(BaseModel):
    actors: list[L9ActorRead] = Field(default_factory=list)
    groups: dict | None = None


class L9MessageRef(BaseModel):
    id: str = ""
    parents: list[str] = Field(default_factory=list)
    episode: str | None = None


class L9ContextRead(BaseModel):
    topic: str | None = None


class L9HeaderRead(BaseModel):
    protocol: str | None = None
    subprotocol: str | None = None
    version: str | None = None
    kind: str
    subkind: str | None = None
    participants: L9ParticipantsRead | None = None
    message: L9MessageRef | None = None
    context: L9ContextRead | None = None


class L9PayloadRead(BaseModel):
    type: str | None = None
    data: dict | None = None


class L9EnvelopeRead(BaseModel):
    """One faithful L9 envelope in an episode's causal chain.

    The sender is the first actor (`header.participants.actors[0].id`) by the
    bus convention in `app.services.l9`; there is deliberately no flattened
    `sender_handle` on the wire envelope — the frontend derives it from actors.
    """

    header: L9HeaderRead
    payload: L9PayloadRead | None = None


class EpisodeMetricsRead(BaseModel):
    mpc: float = 0.0
    gar: float = 0.0
    scr: float = 0.0
    provenance_weight: float = 0.0
    participants: int | None = None


class EpisodeSummaryRead(BaseModel):
    short_id: str
    episode: str
    topic: str
    outcome: str
    subkind: str | None = None
    participants: list[str] = Field(default_factory=list)
    metrics: EpisodeMetricsRead | None = None
    assignments: dict[str, str] | None = None
    plan_file: str | None = None
    message_count: int = 0
    updated_at: str = ""
    updated_by: str = ""


class EpisodeListResponse(BaseModel):
    episodes: list[EpisodeSummaryRead]


class EpisodeDetailRead(EpisodeSummaryRead):
    messages: list[L9EnvelopeRead] = Field(default_factory=list)


# ── Cross-entity search ───────────────────────────────────────────────────────


SearchResultType = Literal["room", "agent", "episode", "memory", "message"]


class SearchScopeRead(BaseModel):
    """How the server read the query's scoping tokens.

    Echoed back so a caller draws its scope chips from the interpretation the
    search actually ran under, rather than re-parsing the string itself.
    """

    text: str = ""
    rooms: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    types: list[SearchResultType] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)


class SearchHitRead(BaseModel):
    """One result, flattened to the shape every entity type shares."""

    type: SearchResultType
    room: str
    id: str = Field(
        ...,
        description="Type-specific identifier to navigate by: memory key, episode "
        "short id, message uuid, room name, agent handle",
    )
    title: str
    subtitle: str = ""
    snippet: str = ""
    kind: str | None = None
    timestamp: str = ""
    score: float


class SearchResponse(BaseModel):
    query: str
    scope: SearchScopeRead
    results: list[SearchHitRead] = Field(default_factory=list)
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Matches per type before the result list was trimmed",
    )
