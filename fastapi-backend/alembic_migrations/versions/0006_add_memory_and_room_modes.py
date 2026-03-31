# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Add persistent memory system and room mode extensions.

Enables pgvector extension, creates memories and memory_subscriptions tables,
and adds mode/trigger/synthesis columns to rooms.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add room mode columns
    op.add_column("rooms", sa.Column("mode", sa.VARCHAR(10), server_default="sync", nullable=False))
    op.add_column("rooms", sa.Column("trigger_config", JSONB, nullable=True))
    op.add_column(
        "rooms", sa.Column("last_synthesis_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "rooms", sa.Column("is_persistent", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("rooms", sa.Column("namespace", sa.String(), nullable=True))

    # Create memories table
    op.create_table(
        "memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("key", sa.String(512), nullable=False, index=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("room_name", "key", name="uq_memory_room_key"),
    )

    # Add vector column via raw SQL (alembic doesn't natively support pgvector types)
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(384)")

    # Create ivfflat index for approximate nearest neighbor search
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_embedding "
        "ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # Create memory_subscriptions table
    op.create_table(
        "memory_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("subscriber", sa.String(), nullable=False, index=True),
        sa.Column("key_pattern", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("memory_subscriptions")
    op.drop_table("memories")
    op.drop_column("rooms", "namespace")
    op.drop_column("rooms", "is_persistent")
    op.drop_column("rooms", "last_synthesis_at")
    op.drop_column("rooms", "trigger_config")
    op.drop_column("rooms", "mode")
    op.execute("DROP EXTENSION IF EXISTS vector")
