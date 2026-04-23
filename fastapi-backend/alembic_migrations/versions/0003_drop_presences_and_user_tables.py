# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Drop presences and user tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop presences table (CLI agent presence — dropped feature)
    op.drop_table("presences")

    # Drop FK from rooms.created_by_id before dropping user table
    op.drop_constraint("rooms_created_by_id_fkey", "rooms", type_="foreignkey")
    op.drop_column("rooms", "created_by_id")

    # Drop user table (fastapi-users auth — dropped feature)
    op.drop_table("user")


def downgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
    )
    op.add_column(
        "rooms",
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "rooms_created_by_id_fkey",
        "rooms",
        "user",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "presences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_handle", sa.String(), nullable=False),
        sa.Column(
            "room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
    )
