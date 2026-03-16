"""
Mycelium data models — 7 core tables.

Workspace, MAS, Agent, Room, Message, Session, AuditEvent.
No auth users, no presence.
"""

from datetime import datetime
from uuid import UUID as UUID_Type
from uuid import uuid4

from sqlalchemy import JSON, VARCHAR, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Uuid as GenericUuid
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── Registry ──────────────────────────────────────────────────────────────────

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MAS(Base):
    """Multi-Agentic System — a named group of agents within a workspace."""
    __tablename__ = "mas"

    id: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID_Type] = mapped_column(
        GenericUuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), primary_key=True, default=uuid4)
    mas_id: Mapped[UUID_Type] = mapped_column(
        GenericUuid(as_uuid=True), ForeignKey("mas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_provider_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    memory_config: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
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
    # Coordination state machine
    coordination_state: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="idle"
    )
    join_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Message(Base):
    """Agent-to-agent messages within a room."""
    __tablename__ = "messages"

    id: Mapped[UUID_Type] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
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

    id: Mapped[UUID_Type] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    room_name: Mapped[str] = mapped_column(
        String, ForeignKey("rooms.name", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_handle: Mapped[str] = mapped_column(String, nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    """Immutable audit trail for CFN resource operations."""
    __tablename__ = "audit_events"

    # Use generic Uuid (not pg-specific) so SQLite works in tests
    id: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), primary_key=True, default=uuid4)
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    audit_type: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_resource_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    audit_information: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    audit_extra_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_modified_by: Mapped[UUID_Type] = mapped_column(GenericUuid(as_uuid=True), nullable=False)
    last_modified_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
