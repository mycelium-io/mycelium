# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Mycelium data models.

Agent, Room, CoordinationSession, Participant, Message, AuditEvent, Memory, MemorySubscription.
"""

from datetime import datetime
from uuid import UUID as UUID_Type
from uuid import uuid4

try:
    from pgvector.sqlalchemy import Vector as _PgVector
    from sqlalchemy import cast, null
    from sqlalchemy.sql.expression import BindParameter

    class Vector(_PgVector):
        """VECTOR that emits an explicit CAST for NULL params.

        asyncpg cannot infer the type for None on a UserDefinedType and
        falls back to BYTEA.  Wrapping NULL with CAST(NULL AS vector) tells
        asyncpg the exact Postgres type so the INSERT succeeds.
        """

        def bind_expression(self, bindvalue: BindParameter):
            # Only wrap when the value is None (NULL); let non-null values pass
            # through the normal bind_processor (returns text '[x,y,...]').
            if bindvalue.value is None and not bindvalue.required:
                return cast(null(), _PgVector(self.dim))
            return bindvalue

except ImportError:
    # Fallback for environments without pgvector (e.g., SQLite tests)
    from sqlalchemy import LargeBinary as Vector

from sqlalchemy import (
    JSON,
    VARCHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as GenericUuid
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── Agent (registered by CFN mgmt plane, memory_provider_url stored here) ─────


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID_Type] = mapped_column(
        GenericUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    mas_id: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_provider_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    memory_config: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Rooms ──────────────────────────────────────────────────────────────────────


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Whether room persists after coordination completes
    is_persistent: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Namespace identifier (defaults to room name)
    namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    # CFN MAS sync — foreign IDs in the cfn_mgmt DB (not FK-constrained)
    mas_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String, nullable=True)


class CoordinationSession(Base):
    """Coordination session — first-class negotiation entity.

    A session is a single negotiation round inside a parent room. State lives
    here; the parent room holds persistent memory and namespace identity.
    Messages addressed to a session use ``messages.coordination_session_id``;
    the parent-room FK stays available for namespace-level chat.
    """

    __tablename__ = "coordination_sessions"
    # At most one non-terminal session per room. Defense in depth against the
    # SELECT-then-INSERT race in ``_spawn_coordination_session`` (#280).
    __table_args__ = (
        Index(
            "ix_coord_sessions_one_active_per_room",
            "parent_room_name",
            unique=True,
            postgresql_where=text("state IN ('idle', 'waiting', 'negotiating')"),
            sqlite_where=text("state IN ('idle', 'waiting', 'negotiating')"),
        ),
    )

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    parent_room_name: Mapped[str] = mapped_column(
        String,
        ForeignKey("rooms.name", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    short_id: Mapped[str] = mapped_column(String(16), nullable=False)
    # State machine: idle | waiting | negotiating | agreed | failed | complete
    state: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default="idle")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    join_window_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Inherited from parent at create time — see issue #237 for context.
    mas_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String, nullable=True)

    @property
    def display_name(self) -> str:
        """Synthesize the legacy ``{parent}:session:{short_id}`` display string.

        Kept for backward compatibility with messages.room_name and any caller
        that still resolves sessions by name.
        """
        return f"{self.parent_room_name}:session:{self.short_id}"


class Message(Base):
    """Agent-to-agent messages within a room."""

    __tablename__ = "messages"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Polymorphic: exactly one of room_name or coordination_session_id is set.
    # room_name → namespace-room messages (chat in a real room).
    # coordination_session_id → negotiation session messages.
    room_name: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("rooms.name", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
        index=True,
    )
    coordination_session_id: Mapped[UUID_Type | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coordination_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Sender/recipient are handles (e.g., "kappa#203b")
    sender_handle: Mapped[str] = mapped_column(String, nullable=False, index=True)
    recipient_handle: Mapped[str | None] = mapped_column(String, index=True)  # NULL = broadcast

    # Type: announce, direct, broadcast, delegate, event
    message_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # ── event primitive (#392) ────────────────────────────────────────────
    # Full structured metadata for message_type="event", returned intact:
    # {kind, ttl_seconds?, status?, payload, provenance[], correlation_id?}.
    # Attribute named event_metadata because Base.metadata is reserved by
    # SQLAlchemy; the column itself is "metadata" per the API contract.
    event_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    # kind/status/expiry are promoted from metadata at write time so the
    # feed (?kind=) and ledger (?status=) filters and the TTL sweep hit
    # plain indexed columns instead of JSON path expressions (which differ
    # between the AgensGraph and SQLite test backends).
    event_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    event_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # created_at + ttl_seconds, precomputed. NULL = durable (never swept).
    event_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        # Feed: newest events of a kind in a room.
        Index("ix_messages_room_kind_created", "room_name", "event_kind", "created_at"),
        # Ledger: open actions/concerns in a room.
        Index("ix_messages_room_kind_status", "room_name", "event_kind", "event_status"),
    )


class Participant(Base):
    """Agent participating in a coordination session — the roster.

    One row per agent join. The CognitiveEngine reads this to learn the list
    of agent handles + intents at tick 0 and to address per-agent ticks during
    a round. The original name ``sessions`` conflated "the negotiation entity"
    with "the agent roster for that negotiation"; renaming clarifies which is
    which.
    """

    __tablename__ = "participants"
    # One participant row per (session, handle). Prevents agent_count
    # double-counting when both the harness/CLI AND the agent itself call
    # ``mycelium session join`` for the same handle (#284).
    __table_args__ = (
        UniqueConstraint(
            "coordination_session_id",
            "agent_handle",
            name="ix_participants_unique_handle_per_session",
        ),
    )

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    coordination_session_id: Mapped[UUID_Type] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coordination_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_handle: Mapped[str] = mapped_column(String, nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Files the agent explicitly shared into the session on join.
    # Shape: [{"path": str, "content": str, "sha256": str}]. Content is
    # opt-in shared context — visible to other participants in the session
    # and forwarded to KXP/CFN like any deliberate room write.
    context_files: Mapped[list | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )


class AuditEvent(Base):
    """Immutable audit trail for CFN resource operations."""

    __tablename__ = "audit_events"

    # Use generic Uuid (not pg-specific) so SQLite works in tests
    id: Mapped[UUID_Type] = mapped_column(
        GenericUuid(as_uuid=True), primary_key=True, default=uuid4
    )
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    audit_type: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_resource_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    audit_information: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    audit_extra_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_modified_by: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), nullable=False)
    last_modified_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Persistent Memory ─────────────────────────────────────────────────────────


class Memory(Base):
    """Persistent memory with optional vector embeddings for semantic search.

    Memories are scoped to a room and shared across all agents in the room.
    """

    __tablename__ = "memories"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_name: Mapped[str] = mapped_column(
        String,
        ForeignKey("rooms.name", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(384), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Filesystem path relative to .mycelium/ data dir
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (UniqueConstraint("room_name", "key", name="uq_memory_room_key"),)


class MemorySubscription(Base):
    """Change notification subscription for memory keys."""

    __tablename__ = "memory_subscriptions"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_name: Mapped[str] = mapped_column(
        String,
        ForeignKey("rooms.name", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    subscriber: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_pattern: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
