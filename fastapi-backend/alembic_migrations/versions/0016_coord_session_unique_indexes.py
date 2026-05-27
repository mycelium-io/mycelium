# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Add partial unique indexes to prevent coordination_session forking and participant double-counting.

Two indexes:

1. ``ix_coord_sessions_one_active_per_room`` — partial unique on
   ``coordination_sessions(parent_room_name)`` filtered to non-terminal
   states (``idle``, ``waiting``, ``negotiating``). Prevents a room from
   ever holding two concurrent active sessions (#280: SELECT-then-INSERT
   race in ``_spawn_coordination_session`` could fork the room).

2. ``ix_participants_unique_handle_per_session`` — unique on
   ``participants(coordination_session_id, agent_handle)``. Prevents the
   same agent from being counted twice in one session, which happens when
   both the harness/CLI AND the agent following SKILL.md call
   ``mycelium session join`` for the same handle (#284: NegMAS sees
   inflated ``agent_count`` and fails quorum).

Both indexes are defense-in-depth alongside application-side fixes
(``pg_advisory_xact_lock`` + ``ON CONFLICT DO UPDATE``).

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Before we can add the unique constraint, drop existing duplicates so the
    # CREATE INDEX doesn't fail on legacy data. Keep the earliest-created row
    # per (parent_room_name, non-terminal state) pair and per
    # (coordination_session_id, agent_handle) pair; cascading FKs handle the
    # downstream cleanup (participants, messages tied to a dropped session).
    op.execute(
        """
        DELETE FROM coordination_sessions a
        USING coordination_sessions b
        WHERE a.parent_room_name = b.parent_room_name
          AND a.state IN ('idle', 'waiting', 'negotiating')
          AND b.state IN ('idle', 'waiting', 'negotiating')
          AND a.created_at > b.created_at;
        """
    )
    op.execute(
        """
        DELETE FROM participants a
        USING participants b
        WHERE a.coordination_session_id = b.coordination_session_id
          AND a.agent_handle = b.agent_handle
          AND a.id > b.id;
        """
    )

    op.create_index(
        "ix_coord_sessions_one_active_per_room",
        "coordination_sessions",
        ["parent_room_name"],
        unique=True,
        postgresql_where=sa.text("state IN ('idle', 'waiting', 'negotiating')"),
    )

    op.create_index(
        "ix_participants_unique_handle_per_session",
        "participants",
        ["coordination_session_id", "agent_handle"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_participants_unique_handle_per_session", table_name="participants")
    op.drop_index("ix_coord_sessions_one_active_per_room", table_name="coordination_sessions")
