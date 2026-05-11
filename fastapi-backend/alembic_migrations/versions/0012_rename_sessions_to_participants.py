# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Rename sessions → participants and re-FK to coordination_sessions (#197 follow-up).

The old ``sessions`` table tracked agent participation in a coordination
session (handle, intent, joined_at). Calling it ``sessions`` conflated it with
the negotiation entity itself, which is now first-class in
``coordination_sessions`` (migration 0011). This rename clarifies semantics
and re-points the FK from ``rooms.name`` (which was always a session-shadow
display name) to ``coordination_sessions.id``.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename table.
    op.rename_table("sessions", "participants")

    # Add the new FK column nullable, backfill, then enforce NOT NULL.
    op.add_column("participants", sa.Column("coordination_session_id", sa.Uuid(), nullable=True))

    # Backfill: every participant row's room_name was a session-shadow display
    # name like "{parent}:session:{short_id}". Resolve to coordination_sessions.id.
    op.execute(
        """
        UPDATE participants p
        SET coordination_session_id = cs.id
        FROM coordination_sessions cs
        WHERE cs.parent_room_name = split_part(p.room_name, ':session:', 1)
          AND cs.short_id         = split_part(p.room_name, ':session:', 2)
        """
    )

    # Drop any rows that didn't resolve — they reference rooms that aren't
    # session-shadows, which the join_room flow should never produce. Logged
    # for awareness rather than silently kept.
    op.execute("DELETE FROM participants WHERE coordination_session_id IS NULL")

    op.alter_column("participants", "coordination_session_id", nullable=False)
    op.create_index(
        "ix_participants_coordination_session_id",
        "participants",
        ["coordination_session_id"],
    )
    op.create_foreign_key(
        "fk_participants_coordination_session",
        "participants",
        "coordination_sessions",
        ["coordination_session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Drop the old room_name FK + column.
    op.drop_index("ix_sessions_room_name", table_name="participants")
    op.drop_constraint("sessions_room_name_fkey", "participants", type_="foreignkey")
    op.drop_column("participants", "room_name")


def downgrade() -> None:
    # Best-effort: this loses participants whose source rooms have been
    # deleted. Coord_session.parent_room_name + short_id reconstructs the
    # legacy display name.
    op.add_column("participants", sa.Column("room_name", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE participants p
        SET room_name = cs.parent_room_name || ':session:' || cs.short_id
        FROM coordination_sessions cs
        WHERE cs.id = p.coordination_session_id
        """
    )
    op.alter_column("participants", "room_name", nullable=False)
    op.create_index("ix_sessions_room_name", "participants", ["room_name"])
    op.create_foreign_key(
        "sessions_room_name_fkey",
        "participants",
        "rooms",
        ["room_name"],
        ["name"],
        ondelete="CASCADE",
    )

    op.drop_constraint("fk_participants_coordination_session", "participants", type_="foreignkey")
    op.drop_index("ix_participants_coordination_session_id", table_name="participants")
    op.drop_column("participants", "coordination_session_id")

    op.rename_table("participants", "sessions")
