# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Make messages.room_name polymorphic with coordination_session_id (#244).

Today every message FKs to ``rooms.name``; for session-bound messages that's
the session-shadow display string ``{parent}:session:{short}``. Before we can
drop shadow rows + the deprecated rooms columns, messages need to address a
session via ``coordination_sessions.id`` directly.

This migration:
1. Makes ``messages.room_name`` nullable.
2. Adds ``messages.coordination_session_id`` as a nullable FK to
   ``coordination_sessions.id`` with CASCADE.
3. Backfills: messages whose ``room_name`` is a session-shadow display string
   move to ``coordination_session_id``; ``room_name`` is NULLed out.
4. Adds a CHECK constraint that exactly one of the two columns is set.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("messages", "room_name", nullable=True)

    op.add_column(
        "messages",
        sa.Column("coordination_session_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_messages_coordination_session_id",
        "messages",
        ["coordination_session_id"],
    )
    op.create_foreign_key(
        "fk_messages_coordination_session",
        "messages",
        "coordination_sessions",
        ["coordination_session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Backfill: route session messages from room_name display string to FK.
    op.execute(
        """
        UPDATE messages m
        SET coordination_session_id = cs.id,
            room_name = NULL
        FROM coordination_sessions cs
        WHERE m.room_name IS NOT NULL
          AND cs.parent_room_name = split_part(m.room_name, ':session:', 1)
          AND cs.short_id         = split_part(m.room_name, ':session:', 2)
          AND split_part(m.room_name, ':session:', 2) <> ''
        """
    )

    # Exactly one of (room_name, coordination_session_id) must be set.
    op.create_check_constraint(
        "ck_messages_one_target",
        "messages",
        "(room_name IS NOT NULL)::int + (coordination_session_id IS NOT NULL)::int = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_one_target", "messages", type_="check")

    # Restore room_name on session messages by reconstructing the display string.
    op.execute(
        """
        UPDATE messages m
        SET room_name = cs.parent_room_name || ':session:' || cs.short_id
        FROM coordination_sessions cs
        WHERE m.coordination_session_id = cs.id
        """
    )

    op.drop_constraint("fk_messages_coordination_session", "messages", type_="foreignkey")
    op.drop_index("ix_messages_coordination_session_id", table_name="messages")
    op.drop_column("messages", "coordination_session_id")

    op.alter_column("messages", "room_name", nullable=False)
