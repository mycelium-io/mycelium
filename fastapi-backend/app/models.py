# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Mycelium data models.

Agent, Room, Message, Session, AuditEvent, Memory, MemorySubscription.
"""

from datetime import datetime
from uuid import UUID as UUID_Type
from uuid import uuid4

try:
    from pgvector.sqlalchemy import Vector as _PgVector
    from sqlalchemy import cast, null
    from sqlalchemy.sql.expression import BindParameter

    class Vector(_PgVector):  # type: ignore[misc]
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
    from sqlalchemy import LargeBinary as Vector  # type: ignore[assignment]

from sqlalchemy import (
    JSON,
    VARCHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
    # Coordination state machine: idle | waiting | negotiating | complete | synthesizing
    coordination_state: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="idle"
    )
    join_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Legacy column — kept for migration compat. Always "async" for rooms, "sync" for sessions.
    mode: Mapped[str] = mapped_column(
        VARCHAR(10), nullable=False, server_default="async", default="async"
    )
    # Trigger config for async CognitiveEngine activation
    # e.g. {"type": "threshold", "min_contributions": 5}
    # or   {"type": "schedule", "cron": "0 */6 * * *"}
    # or   {"type": "explicit"}
    trigger_config: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    # Last time CognitiveEngine ran async synthesis
    last_synthesis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Whether room persists after coordination completes
    is_persistent: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Namespace identifier (defaults to room name)
    namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    # True for persistent namespaces (async rooms), False for ephemeral sessions (sync)
    is_namespace: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # For sessions spawned within a namespace, points to the parent room name.
    # No FK constraint — validated in application code to avoid AgensGraph create_all ordering issues.
    parent_namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    # CFN MAS sync — foreign IDs in the cfn_mgmt DB (not FK-constrained)
    mas_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Message(Base):
    """Agent-to-agent messages within a room."""

    __tablename__ = "messages"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_name: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.name", ondelete="CASCADE"), nullable=False, index=True
    )

    # Sender/recipient are handles (e.g., "kappa#203b")
    sender_handle: Mapped[str] = mapped_column(String, nullable=False, index=True)
    recipient_handle: Mapped[str | None] = mapped_column(String, index=True)  # NULL = broadcast

    # Type: announce, direct, broadcast, delegate
    message_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Session(Base):
    """Agent presence in a room — tracks who has joined."""

    __tablename__ = "sessions"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_name: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.name", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_handle: Mapped[str] = mapped_column(String, nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)


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

    Memories have a scope:
      - "namespace" (default): shared, visible to all agents in the room
      - "notebook": private to a specific agent handle
    """

    __tablename__ = "memories"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_name: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.name", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(384), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    tags: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "namespace" (shared) or "notebook" (agent-private)
    scope: Mapped[str] = mapped_column(VARCHAR(20), server_default="namespace", nullable=False)
    # For notebook-scoped memories, the owning agent handle
    owner_handle: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Filesystem path relative to .mycelium/ data dir
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (
        UniqueConstraint("room_name", "key", "scope", "owner_handle", name="uq_memory_scope_key"),
    )


class MemorySubscription(Base):
    """Change notification subscription for memory keys."""

    __tablename__ = "memory_subscriptions"

    id: Mapped[UUID_Type] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_name: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.name", ondelete="CASCADE"), nullable=False, index=True
    )
    subscriber: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_pattern: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
