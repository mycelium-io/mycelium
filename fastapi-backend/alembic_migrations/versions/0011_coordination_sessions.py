# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Promote sessions to first-class entity (#197).

Creates the coordination_sessions table and backfills it from existing
session-shaped rows in `rooms` (is_namespace=False, parent_namespace IS NOT NULL).

Backwards compat: the session-shadow rows in `rooms` are kept so that
messages.room_name and memories.room_name FKs continue to resolve. A follow-up
release will remove the shadow rows and the deprecated columns
(is_namespace, mode, parent_namespace).

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coordination_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "parent_room_name",
            sa.String(),
            sa.ForeignKey("rooms.name", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("short_id", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("join_window_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mas_id", sa.String(), nullable=True, index=True),
        sa.Column("workspace_id", sa.String(), nullable=True),
    )

    # Backfill: every session-shadow row in `rooms` becomes a coordination_sessions row.
    # short_id is the suffix after `:session:` in the room name (8-char hex by convention).
    # Skip orphans whose parent_namespace no longer exists in `rooms` — they would
    # violate the FK we just declared. Surface them via NOTICE so operators know.
    orphans = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT name, parent_namespace FROM rooms
                WHERE is_namespace = FALSE
                  AND parent_namespace IS NOT NULL
                  AND parent_namespace NOT IN (SELECT name FROM rooms)
                """
            )
        )
        .fetchall()
    )
    if orphans:
        names = ", ".join(f"{n} (orphan parent={p})" for n, p in orphans)
        print(f"[0011] Skipping {len(orphans)} orphan session row(s): {names}")

    op.execute(
        """
        INSERT INTO coordination_sessions
            (id, parent_room_name, short_id, state, created_at, join_window_ends_at, mas_id, workspace_id)
        SELECT
            gen_random_uuid(),
            parent_namespace,
            COALESCE(NULLIF(split_part(name, ':session:', 2), ''), substr(md5(name), 1, 8)),
            COALESCE(coordination_state, 'idle'),
            created_at,
            join_deadline,
            mas_id,
            workspace_id
        FROM rooms
        WHERE is_namespace = FALSE
          AND parent_namespace IS NOT NULL
          AND parent_namespace IN (SELECT name FROM rooms)
        """
    )


def downgrade() -> None:
    op.drop_table("coordination_sessions")
