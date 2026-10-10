# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Minimal schemas for Mycelium's core models.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

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
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description=(
            "Room name: 1-100 printable characters; path separators, blank names, "
            "'.', '..', and the reserved ':session:' marker are not allowed"
        ),
    )
    description: str | None = Field(None, max_length=500)
    title: str | None = Field(None, max_length=200)
    is_public: bool = Field(
        True,
        description="Shared (listed for everyone) or private (listed for its owner and members)",
    )
    owner: str | None = Field(
        None, description="Who created it; a private room is always listed for its owner"
    )
    members: list[str] = Field(
        default_factory=list, description="Who else a private room is listed for"
    )
    mas_id: str | None = None
    workspace_id: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Keep a room name safe as one filesystem and SLIM namespace segment."""
        if not value.strip():
            raise ValueError("Room name must not be blank")
        if value in {".", ".."}:
            raise ValueError("Room name must not be '.' or '..'")
        if "/" in value or "\\" in value:
            raise ValueError("Room name must not contain path separators")
        if ":session:" in value:
            raise ValueError("Room name must not contain the reserved ':session:' marker")
        if not value.isprintable():
            raise ValueError("Room name must contain only printable characters")
        return value


class RoomRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    #: The room's display title — the italic hero the app draws above the board.
    #: Room metadata rather than a memory: it names the room, it is not work in
    #: it, and nothing projects it as a row.
    title: str | None = None
    is_public: bool
    #: Who created it. A private room (``is_public`` false) is listed only for
    #: its owner and ``members``; see ``services/room_access.py``.
    owner: str | None = None
    members: list[str] = Field(default_factory=list)
    created_at: datetime
    #: When the room was last active (its transcript's mtime), or ``created_at``
    #: for a room with no messages yet. Populated by ``GET /rooms``.
    last_activity: datetime | None = None
    is_persistent: bool = False
    mas_id: str | None = None
    workspace_id: str | None = None
    #: The pattern the room was loaded from, and the task its flow runs in;
    #: unset for a room made any other way.
    pattern: str | None = None
    pattern_task: str | None = None

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


# The message types whose ``content`` is human-readable prose — real chat, and
# the only part of a room's feed a reader can distill for meaning. Everything
# else the feed carries is structured: the ``l9_*`` raise-up frames hold a
# serialized envelope as their content, and the coordination/plan kinds are
# lifecycle markers. A consumer that reads the transcript for what was *said*
# (the synthesizer) filters on this table rather than sniffing payloads, so a
# new system kind is excluded by default instead of leaking JSON into a prompt.
PROSE_MESSAGE_TYPES: frozenset[str] = frozenset(
    {
        MessageType.ANNOUNCE,
        MessageType.DIRECT,
        MessageType.BROADCAST,
        MessageType.DELEGATE,
    }
)


# The message types a client may create over the HTTP API. The system-posted
# kinds above are written server-side and are not accepted on inbound requests.
ApiMessageType = Literal[
    MessageType.ANNOUNCE,
    MessageType.DIRECT,
    MessageType.BROADCAST,
    MessageType.DELEGATE,
    MessageType.EVENT,
]


# ── event primitive ───────────────────────────────────────────────────────────

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
    episode: str | None = Field(
        None,
        description=(
            "Thread to post into (an episode URN — a task's, or a negotiation "
            "inside one). Omit to post to the room itself."
        ),
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
        None, description="episode URN this message belongs to, if any (for grouping/folding)"
    )
    edited_at: datetime | None = Field(
        None,
        description=(
            "When this message was last revised by an amendment, folded in on read. "
            "None for a message nobody amended."
        ),
    )
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class MessageAmend(BaseModel):
    """A revision of an earlier message: new text, same author.

    The amendment is posted as its own ``exchange:amend`` message parented on the
    one it revises. Nothing in the transcript is rewritten — the read path folds
    the chain to the newest text.
    """

    content: str = Field(..., min_length=1, description="The revised message text")
    sender_handle: str | None = Field(
        None,
        description=(
            "Handle amending; must be the original sender. Defaults to the token-verified caller."
        ),
    )


class MessageListResponse(BaseModel):
    messages: list[MessageRead]
    total: int


class MessageSearchClause(BaseModel):
    """One ``field:value`` the search narrowed by, as the server read it."""

    field: str
    value: str
    negate: bool = False


class MessageSearchScope(BaseModel):
    """The interpretation a message search ran under, echoed so a client draws
    its chips from the same parse the server used."""

    text: str = ""
    clauses: list[MessageSearchClause] = Field(default_factory=list)
    after: datetime | None = None
    before: datetime | None = None
    sort: Literal["newest", "oldest", "relevance"] = "newest"
    problems: list[str] = Field(
        default_factory=list,
        description="Tokens that looked like a field or a time but could not be read, as typed",
    )


class FacetBucket(BaseModel):
    value: str
    label: str = Field(..., description="What to show for the value (a task's title for its key)")
    count: int


class MessageSearchHit(BaseModel):
    message: MessageRead
    snippet: str = Field(..., description="A one-line window of the text around the first match")
    score: float = 0.0
    task_key: str | None = Field(None, description="The board row whose thread it was said in")
    task_title: str | None = None
    thread: str | None = Field(
        None, description="The thread's episode URN; null when said in the room"
    )
    recipients: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    stance: str | None = None
    context_before: list[MessageRead] = Field(default_factory=list)
    context_after: list[MessageRead] = Field(default_factory=list)


class MessageSearchResponse(BaseModel):
    query: str
    scope: MessageSearchScope
    hits: list[MessageSearchHit] = Field(default_factory=list)
    total: int = Field(..., description="Every message the query matched, before paging")
    scanned: int = Field(..., description="Messages the search read")
    facets: dict[str, list[FacetBucket]] = Field(
        default_factory=dict,
        description=(
            "Counts per field value. A field's counts ignore that field's own clauses, "
            "so its other values stay visible as alternatives"
        ),
    )
    fields: list[str] = Field(default_factory=list, description="Every field the grammar accepts")
    next_cursor: str | None = Field(None, description="Pass as `cursor` to read the next page")


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
    meta: dict[str, Any] | None = Field(
        None,
        description=(
            "The memory's unmanaged frontmatter — every key the store doesn't own "
            "(so not key, authorship, version, timestamps, tags or value). This is "
            "what ``MemoryCreate.meta`` wrote, read back."
        ),
    )
    episode: str | None = Field(
        None,
        description=(
            "The episode URN the conversation about this memory happens in — what "
            "makes a task a thread, and what makes every other memory "
            "discussable. Every memory carries one, whatever its namespace and "
            "whoever wrote it. Store-owned: minted by the backend on create, so "
            "it is absent from ``meta`` and cannot be set by a write. Null only "
            "on a memory written before threading and not yet backfilled."
        ),
    )
    expandable: bool = Field(
        False,
        description=(
            "Whether this memory opts in to transclusion via ``![[key]]``. "
            "Mirrors the ``expandable`` frontmatter flag, which is also in ``meta``."
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


class UploadRead(BaseModel):
    """A file the room keeps: an ``uploads/<name>`` memory and the bytes it names."""

    name: str = Field(
        ..., description="The upload's name in the room, unique there; its URL segment"
    )
    key: str = Field(..., description="The memory key, `uploads/<name>`; link it as [[key]]")
    filename: str = Field(..., description="The name the file had when it was added, for download")
    kind: Literal["image", "pdf", "text", "audio", "video"]
    content_type: str = Field(..., description="The type the file is served as")
    size: int = Field(..., description="Size in bytes, after cleaning")
    sha256: str
    created_by: str
    created_at: datetime
    episode: str | None = Field(None, description="The upload's own thread, as every memory has")
    url: str = Field(..., description="Path of the file's bytes on this hub, under /api")


class UploadListResponse(BaseModel):
    uploads: list[UploadRead]
    total: int
    accepted: list[str] = Field(
        default_factory=list, description="The file extensions this hub takes, lowercase, no dot"
    )
    max_bytes: int = Field(0, description="The largest file this hub takes, in bytes")


class VoiceStatus(BaseModel):
    """Whether this hub can transcribe a mic, and what it hears."""

    state: Literal["ready", "not_downloaded", "unavailable"] = Field(
        ...,
        description=(
            "`ready`: the model is loaded or on disk. `not_downloaded`: it will be "
            "fetched the first time a mic is turned on. `unavailable`: it can't run here."
        ),
    )
    detail: str = Field("", description="Why, when it isn't ready")
    language: str = Field("en", description="The language it transcribes")
    sample_rate: int = Field(16000, description="The rate audio is sent at, in Hz")
    model: str = Field("", description="The speech model's name")


class VoiceHeard(BaseModel):
    """What one chunk of a mic's audio finished: text for the draft, if any."""

    texts: list[str] = Field(
        default_factory=list, description="Each piece of speech the chunk ended, in order"
    )
    speaking: bool = Field(False, description="Whether speech is still under way")
    ready: bool = Field(
        True,
        description=(
            "False while the hub loads (or downloads) its speech model: the chunk "
            "wasn't read, so send the same audio again"
        ),
    )


class ProtocolSummary(BaseModel):
    """A flow the room's conductor can run, as a summon needs to know it."""

    name: str
    description: str = ""
    roles: list[str] = Field(
        default_factory=list,
        description="Bound in order to the members a summon names; empty means everyone who is named.",
    )
    source: Literal["builtin", "room"] = Field(
        ..., description="`room` when the room's protocols/<name> memory defines or reshapes it."
    )


# ── Principal (self-asserted user store) ──────────────────────────────────────
# The human made first-class, symmetric with agents/<handle>. An agent's owner
# points at a users/<handle>; a team groups these handles. Trust is self-asserted
# — the handle is consistent, not cryptographic.


class UserCreate(BaseModel):
    handle: str = Field(..., min_length=1, pattern=HANDLE_PATTERN)
    display_name: str = ""
    teams: list[str] = Field(default_factory=list)
    notify: str | None = None
    #: Who registered the record, stamped into its frontmatter. Optional so a
    #: caller that has no principal to name (the GUI) keeps the "system" default.
    created_by: str | None = None


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


class RoomFolder(BaseModel):
    """One of a person's folders in their rooms list, and the rooms filed in it."""

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=64)
    rooms: list[str] = Field(default_factory=list, max_length=500)
    #: Folded in the sidebar; remembered with the folder so it stays folded.
    collapsed: bool = False


class RoomFolders(BaseModel):
    """How one person organizes their rooms list: theirs alone, not the room's.

    A room sits in at most one folder; rooms in none are listed as before.
    A name that no longer names a room is kept, and simply not drawn.
    """

    folders: list[RoomFolder] = Field(default_factory=list, max_length=100)


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
    # An agent a runner started on someone's machine: which machine, and which
    # agent CLI it runs there. None for every agent the hub did not start that way.
    runner: str | None = None
    framework: str | None = None


# ── Runners (a user's machine, dialed in) ────────────────────────────────────
#
# A runner is `mycelium runner` on someone's computer. It dials out to the hub,
# says which agent CLIs it found there, and takes jobs the app queues for it.
# The hub never reaches into the machine: everything it asks for is a job the
# runner chose to poll for, naming a framework from the runner's own scan.
# Every agent a runner starts is an interactive session in a herdr pane.

RunnerAgentStatus = Literal[
    "starting", "running", "idle", "working", "blocked", "stopped", "failed"
]
RunnerJobKind = Literal["launch", "stop", "scan", "swarm", "restart", "pair"]
#: ``waiting``: the runner took it and is asking the person at that machine first.
RunnerJobStatus = Literal["queued", "running", "waiting", "done", "failed"]


class FrameworkRead(BaseModel):
    """One agent CLI a runner knows about, found on its machine or not."""

    id: str
    name: str
    command: str
    path: str | None = None
    version: str | None = None
    installed: bool = False
    launchable: bool = Field(False, description="herdr can start it in a pane")
    note: str | None = None


class RunnerAgentRead(BaseModel):
    """An agent a runner started in a herdr pane and is keeping track of."""

    handle: str
    room: str
    framework: str
    status: RunnerAgentStatus = "starting"
    pane: str | None = None
    cwd: str | None = None
    started_at: datetime
    detail: str | None = None


class RunnerAgentRef(BaseModel):
    handle: str = Field(..., min_length=1, max_length=64)
    room: str | None = None


class MachineAgentRead(BaseModel):
    """One herdr agent on a machine, however it got there (``mycelium machine``)."""

    handle: str
    room: str
    pane: str
    state: Literal["working", "idle", "blocked", "stopped", "gone", "unknown"] = Field(
        ..., description="stopped: its pane is open with nothing running in it; gone: closed"
    )
    kind: str | None = Field(None, description="The agent CLI, as herdr names its kind")
    folder: str | None = None
    workspace: str | None = None
    restores: bool | None = Field(
        None, description="Whether herdr brings it back after herdr restarts; null when unknown"
    )
    restartable: bool = Field(
        False, description="Stopped or gone, with a folder and CLI to restart"
    )


class MachineWorkspaceRead(BaseModel):
    """A herdr workspace on a machine, and the room it's bound to."""

    id: str
    label: str
    room: str | None = None
    agents: list[MachineAgentRead] = Field(default_factory=list)


class MachineProblemRead(BaseModel):
    """Something wrong on a machine, and the CLI command that fixes it."""

    kind: Literal[
        "stopped",
        "lost",
        "runner_down",
        "wakes_stalled",
        "binding_failing",
        "no_restore",
        "herdr_update",
        "herdr_down",
    ]
    text: str
    fix: str | None = None
    handles: list[str] = Field(default_factory=list)


class MachineReportRead(BaseModel):
    """Every agent on a machine and what's wrong (``mycelium machine``'s report)."""

    machine: str
    herdr: bool = False
    herdr_server: str | None = None
    herdr_client: str | None = None
    herdr_minimum: str | None = Field(None, description="The oldest herdr Mycelium works with")
    runner: bool = Field(True, description="Whether its runner is running (it keeps agents synced)")
    missing_integrations: list[str] = Field(
        default_factory=list, description="herdr integrations not current for agents running here"
    )
    workspaces: list[MachineWorkspaceRead] = Field(default_factory=list)
    problems: list[MachineProblemRead] = Field(default_factory=list)


class DeviceSignature(BaseModel):
    """A paired device's signature over a job it asked for, which the hub only carries.

    ``body`` is the exact JSON the device signed (the runner, the job's kind
    and fields, a time and a nonce); ``sig`` is ECDSA P-256 over it, ``r||s``
    in base64url. The runner checks both against the job it receives, and
    starts it without asking only when they hold (``mycelium/runner/pairing.py``).
    """

    key: str = Field(..., min_length=8, max_length=64, description="The device key's id")
    body: str = Field(..., min_length=2, max_length=8192)
    sig: str = Field(..., min_length=8, max_length=200)


class MachineRestart(BaseModel):
    """Agents to restart on a machine: some by handle, or every stopped one."""

    agents: list[RunnerAgentRef] = Field(default_factory=list)
    all: bool = False
    signature: DeviceSignature | None = Field(
        None, description="From a device paired with the machine: starts without asking there"
    )


class RunnerPairingRead(BaseModel):
    """A device paired with a runner, and what the pairing covers (set on that machine)."""

    name: str
    key: str = Field(..., description="The device key's id, which the device also knows")
    paired_at: datetime
    expires_at: datetime | None = None
    folders: list[str] = Field(
        default_factory=list, description="Folders it covers; empty: every root"
    )
    clis: list[str] = Field(default_factory=list, description="Agent CLIs it covers; empty: any")
    swarms: bool = False


class PairingOutcome(BaseModel):
    """Whether a signed job started under a pairing, or why it waits for a yes after all."""

    accepted: bool
    name: str | None = Field(None, description="The pairing it started under")
    reason: str | None = Field(None, description="Why the signature wasn't enough")


class DeviceKey(BaseModel):
    """A P-256 public key as a JWK's coordinates."""

    x: str = Field(..., min_length=40, max_length=50)
    y: str = Field(..., min_length=40, max_length=50)


class RunnerPair(BaseModel):
    """A device asking to pair with the machine that printed a code.

    Only the code's first four characters are sent, to find the machine; the
    rest keys ``proof``, an HMAC over the device's name and key, which only
    the machine can check.
    """

    code_id: str = Field(..., min_length=4, max_length=4)
    name: str = Field(..., min_length=1, max_length=40)
    key: DeviceKey
    proof: str = Field(..., min_length=40, max_length=50)


class RunnerSyncRead(BaseModel):
    """How a runner's sync pass (presence up, wakes down) is doing."""

    #: When the last pass finished, by the runner's clock; None before the first.
    last_pass_at: datetime | None = None
    last_pass_ms: int | None = None
    #: How long the pass running now has run; None between passes. Past
    #: ``stall_s`` the runner is stuck and delivers no wakes.
    running_s: float | None = None
    stall_s: float | None = None
    #: Why the last pass failed, when it did.
    error: str | None = None


class RunnerHello(BaseModel):
    """What a runner says about itself when it dials in, and on every heartbeat."""

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str = Field(..., min_length=1, max_length=120)
    owner: str | None = None
    platform: str = ""
    version: str = ""
    #: Whether the runner's host is up. Named ``herdr``, which predates hosts.
    herdr: bool = False
    #: The host the runner starts agents on, by name. A runner that doesn't say is herdr's.
    host: str = "herdr"
    roots: list[str] = Field(default_factory=list)
    frameworks: list[FrameworkRead] = Field(default_factory=list)
    agents: list[RunnerAgentRead] = Field(default_factory=list)
    #: Every agent on the machine, whoever started it, and what's wrong. None
    #: from a runner from before it sent one.
    machine: MachineReportRead | None = None
    #: How its sync pass is doing. None from a runner from before it sent one.
    sync: RunnerSyncRead | None = None
    #: Devices whose signed requests it starts without asking.
    pairings: list[RunnerPairingRead] = Field(default_factory=list)
    #: The public ids of its live pairing codes, for routing a pair request.
    pairing_offers: list[str] = Field(default_factory=list, max_length=8)


class RunnerRead(RunnerHello):
    """A runner as the app sees it."""

    #: Not shown: anyone listing runners could otherwise use up a code's tries.
    pairing_offers: SkipJsonSchema[list[str]] = Field(default_factory=list, exclude=True)
    connected: bool
    last_seen: datetime
    started_at: datetime


class RunnerJobRead(BaseModel):
    """Something the hub asked a runner to do, and how it went."""

    id: str
    runner: str
    kind: RunnerJobKind
    spec: dict[str, Any] = Field(default_factory=dict)
    status: RunnerJobStatus = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    signature: DeviceSignature | None = None
    pairing: PairingOutcome | None = None


class RunnerJobReport(BaseModel):
    """A runner reporting on a job it took."""

    status: RunnerJobStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    pairing: PairingOutcome | None = None


class RunnerAgentLaunch(BaseModel):
    """Start an agent on a runner's machine, as a member of a room."""

    room: str = Field(..., min_length=1)
    handle: str = Field(..., min_length=1, max_length=64)
    framework: str = Field(..., min_length=1, description="A framework id from the runner's scan")
    instructions: str | None = Field(
        None, description="How the agent should work; saved as its notes, which it reads first"
    )
    description: str = ""
    cwd: str | None = Field(None, description="Folder to start it in; inside one of the roots")
    worktree: bool = Field(False, description="Start it in its own git worktree of cwd")
    created_by: str | None = None
    signature: DeviceSignature | None = Field(
        None, description="From a device paired with the machine: starts without asking there"
    )


# ── Join codes ───────────────────────────────────────────────────────────────


class JoinCreate(BaseModel):
    """Ask for a code an agent can redeem to become ``handle`` in the room."""

    handle: str = Field(..., min_length=1, max_length=64)


class JoinRead(BaseModel):
    """A new join code. Single-use; show it only to the agent it is for."""

    code: str
    room: str
    handle: str
    expires_at: datetime


class JoinRedeem(BaseModel):
    code: str = Field(..., min_length=4, max_length=64)


class MembershipRead(BaseModel):
    """What a redeemed code makes the caller: a member of a room, with a token when the hub needs one."""

    room: str
    handle: str
    token: str | None = Field(
        None, description="A token the hub signed for this member; null when the hub's auth is off"
    )
    token_expires_at: datetime | None = None


# ── A2A bridge state (the Network views) ─────────────────────────────────────
#
# What the GUI's Network pane and `mycelium network` need to render the bridge
# next to SLIM traffic: who is bridged, whether the room is discoverable as an
# A2A agent, and the recent exchanges. The honest boundary — a bridged agent is
# proxied by this hub, never a member of the room's MLS group — is carried by
# `proxied` so both surfaces state it from the same field rather than each
# inventing its own copy.


class A2aExchangeRead(BaseModel):
    """One bridged turn: a call we made out, or a message that arrived in."""

    id: str
    handle: str
    direction: str  # outbound | inbound
    status: str  # ok | error
    at: datetime
    endpoint: str | None = None
    #: Whose ``@``-mention triggered the call (outbound only).
    peer: str | None = None
    prompt: str = ""
    reply: str = ""
    detail: str | None = None
    duration_ms: int | None = None


class A2aBridgedAgentRead(BaseModel):
    """A room member reached over A2A rather than the room's SLIM channel."""

    handle: str
    description: str = ""
    card: str | None = None
    endpoint: str | None = None
    skills: list[str] = Field(default_factory=list)
    calls_ok: int = 0
    calls_failed: int = 0
    last_call_at: datetime | None = None
    #: Always true, and stated rather than implied: the hub proxies this agent
    #: over HTTP, so it holds no group key and is not an MLS group member.
    proxied: bool = True


class A2aExposureRead(BaseModel):
    """The inbound half: this room served as an A2A agent of its own."""

    card_url: str
    rpc_url: str
    skills: list[str] = Field(default_factory=list)
    card_fetches: int = 0
    messages: int = 0
    last_card_fetch_at: datetime | None = None
    last_message_at: datetime | None = None


class A2aBridgeState(BaseModel):
    """Everything the Network views show about a room's A2A bridge."""

    room: str
    agents: list[A2aBridgedAgentRead] = Field(default_factory=list)
    exposure: A2aExposureRead
    exchanges: list[A2aExchangeRead] = Field(default_factory=list)
    outbound_ok: int = 0
    outbound_failed: int = 0


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


# ── episodes (protocol inspector) ─────────────────────────────────────────
#
# The episode read API projects persisted episode records into JSON the UI
# inspector renders. These models are the typed seam: the backend routes declare
# them as `response_model`, so FastAPI validates + filters the raw parsed dicts
# into exactly this shape. They mirror the frontend `MyceliumMessage` / `EpisodeDetail`
# TypeScript interfaces 1:1, so neither side can silently read a field the other
# doesn't send. Fields are permissive (most optional) because these records are
# historical markdown files, not freshly minted objects — a single odd envelope
# must not 500 the whole inspector. The one invariant: every envelope has a kind.


class EnvelopeActorRead(BaseModel):
    id: str
    role: str


class EnvelopeParticipantsRead(BaseModel):
    actors: list[EnvelopeActorRead] = Field(default_factory=list)
    groups: dict | None = None


class EnvelopeMessageRef(BaseModel):
    id: str = ""
    parents: list[str] = Field(default_factory=list)
    episode: str | None = None


class EnvelopeContextRead(BaseModel):
    topic: str | None = None


class EnvelopeHeaderRead(BaseModel):
    protocol: str | None = None
    subprotocol: str | None = None
    version: str | None = None
    kind: str
    subkind: str | None = None
    participants: EnvelopeParticipantsRead | None = None
    message: EnvelopeMessageRef | None = None
    context: EnvelopeContextRead | None = None


class EnvelopePayloadRead(BaseModel):
    type: str | None = None
    data: dict | None = None


class EnvelopeRead(BaseModel):
    """One faithful message in an episode's causal chain.

    The sender is the first actor (`header.participants.actors[0].id`) by the
    bus convention in `app.services.message_format`; there is deliberately no flattened
    `sender_handle` on the wire envelope — the frontend derives it from actors.
    """

    header: EnvelopeHeaderRead
    payload: EnvelopePayloadRead | None = None


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
    #: Memory keys of the ``work/`` rows the agreement compiled into.
    tasks: list[str] = Field(default_factory=list)
    message_count: int = 0
    updated_at: str = ""
    updated_by: str = ""
    #: The thread this episode was opened from, when it runs inside a task.
    within: str | None = None
    #: The interaction flow this episode runs (roles, steps, edges, bindings),
    #: for an episode the conductor walks; ``None`` for a negotiation or a thread.
    flow: dict[str, Any] | None = None
    #: One entry per step taken, in order — written as the run walks.
    trace: list[dict[str, Any]] = Field(default_factory=list)
    #: Where an open run stands, read off the trace.
    current_step: str | None = None


class EpisodeListResponse(BaseModel):
    episodes: list[EpisodeSummaryRead]


class EpisodeDetailRead(EpisodeSummaryRead):
    messages: list[EnvelopeRead] = Field(default_factory=list)


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


# ── Schedules ─────────────────────────────────────────────────────────────────

ScheduleResult = Literal["woke", "quiet", "held", "busy", "error"]


class ScheduleCreate(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=64, pattern=SLUG_PATTERN, description="Schedule slug"
    )
    owner: str = Field(..., description="The agent the schedule wakes")
    every: str | None = Field(None, description="An interval like 30m, 2h or 1d")
    cron: str | None = Field(None, description="A five-field cron line, read in UTC")
    prompt: str = Field("", max_length=4000, description="What the owner is told when it wakes")
    check: str | None = Field(
        None,
        description=(
            "The pre-check that decides whether the owner wakes: always, mentions, "
            "assigned, stale, silent, task, or search:<query>"
        ),
    )
    task: str | None = Field(None, description="A board row the schedule is bound to")
    expires_in_days: float | None = Field(
        None, description="How long until it has to be renewed (hub default when omitted)"
    )
    created_by: str | None = Field(None, description="Who is setting it up")


class ScheduleUpdate(BaseModel):
    every: str | None = None
    cron: str | None = None
    prompt: str | None = None
    check: str | None = None
    task: str | None = Field(None, description="A row key, or an empty string to unbind")
    paused: bool | None = None
    renew: bool = Field(False, description="Start its expiry again from now")
    renew_days: float | None = Field(None, description="Renew for this many days")


class ScheduleRunRequest(BaseModel):
    wake: bool = Field(False, description="Skip the pre-check and wake the owner")


class ScheduleRunRead(BaseModel):
    at: datetime
    result: ScheduleResult
    trigger: Literal["schedule", "manual"]
    missed: int = 0
    found: list[str] = []
    found_total: int = 0
    detail: str | None = None


class ScheduleRead(BaseModel):
    name: str
    owner: str
    every: str | None = None
    cron: str | None = None
    prompt: str = ""
    check: str
    task: str | None = None
    state: Literal["active", "paused", "expired"]
    paused: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    next_run: datetime | None = None
    last_run: datetime | None = None
    last_result: ScheduleResult | None = None
    runs: int = 0
    wakes: int = Field(0, description="Runs that woke the owner: each one is a model turn")
    quiet: int = Field(0, description="Runs whose pre-check found nothing, costing no turn")
    history: list[ScheduleRunRead] = []


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleRead]
    total: int
    checks: dict[str, str] = Field(
        default_factory=dict, description="The pre-checks the hub runs, and what each finds"
    )
