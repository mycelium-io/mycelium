"""Initial schema — users, rooms, messages, sessions, presences.

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── users (fastapi-users base table) ─────────────────────────────────────
    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)

    # ── rooms ─────────────────────────────────────────────────────────────────
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rooms_name"), "rooms", ["name"], unique=True)

    # ── messages ──────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_handle", sa.String(), nullable=False),
        sa.Column("recipient_handle", sa.String(), nullable=True),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_room_name"), "messages", ["room_name"])
    op.create_index(op.f("ix_messages_sender_handle"), "messages", ["sender_handle"])
    op.create_index(op.f("ix_messages_recipient_handle"), "messages", ["recipient_handle"])
    op.create_index(op.f("ix_messages_message_type"), "messages", ["message_type"])
    op.create_index(op.f("ix_messages_created_at"), "messages", ["created_at"])

    # ── sessions ──────────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_handle", sa.String(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_room_name"), "sessions", ["room_name"])
    op.create_index(op.f("ix_sessions_agent_handle"), "sessions", ["agent_handle"])

    # ── presences ─────────────────────────────────────────────────────────────
    op.create_table(
        "presences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_handle", sa.String(), nullable=False),
        sa.Column(
            "room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="online"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_presences_agent_handle"), "presences", ["agent_handle"])
    op.create_index(op.f("ix_presences_room_name"), "presences", ["room_name"])


def downgrade() -> None:
    op.drop_table("presences")
    op.drop_table("sessions")
    op.drop_table("messages")
    op.drop_table("rooms")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
