# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Drop session-shadow rows + deprecated rooms columns (#244 final).

After 0013, messages can FK to coordination_sessions directly. The session
shadow rows in ``rooms`` are no longer needed. This migration:
1. Deletes shadow rows (parent_namespace IS NOT NULL).
2. Drops the ``join_deadline`` column from rooms (state lives on
   ``coordination_sessions.join_window_ends_at``).
3. Drops ``is_namespace``, ``mode``, ``parent_namespace`` from rooms.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete shadow rows. coordination_sessions, participants, and any
    # session-keyed messages are unaffected because they FK to
    # coordination_sessions.id, not to rooms.name. Messages whose room_name
    # still pointed at a shadow were migrated to coordination_session_id in
    # 0013, so cascading the shadow deletion here is safe.
    op.execute("DELETE FROM rooms WHERE parent_namespace IS NOT NULL OR is_namespace = FALSE")

    # Drop the index on parent_namespace if any tooling created one.
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("join_deadline")
        batch.drop_column("parent_namespace")
        batch.drop_column("mode")
        batch.drop_column("is_namespace")


def downgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(
            sa.Column("is_namespace", sa.Boolean(), nullable=False, server_default="true")
        )
        batch.add_column(
            sa.Column("mode", sa.String(length=10), nullable=False, server_default="async")
        )
        batch.add_column(sa.Column("parent_namespace", sa.String(), nullable=True))
        batch.add_column(sa.Column("join_deadline", sa.DateTime(timezone=True), nullable=True))
