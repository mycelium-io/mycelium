# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Add notebook scope to memories and namespace fields to rooms.

Adds scope/owner_handle columns to memories for notebook (agent-private)
vs namespace (shared) memory. Adds is_namespace/parent_namespace to rooms
to distinguish persistent namespaces from ephemeral sessions.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Memory scope: "namespace" (shared) or "notebook" (agent-private)
    op.add_column(
        "memories",
        sa.Column("scope", sa.VARCHAR(20), server_default="namespace", nullable=False),
    )
    # Owner handle for notebook-scoped memories (NULL for namespace memories)
    op.add_column(
        "memories",
        sa.Column("owner_handle", sa.String(), nullable=True, index=True),
    )

    # Drop old unique constraint and create new one that includes scope + owner
    op.drop_constraint("uq_memory_room_key", "memories", type_="unique")
    op.create_unique_constraint(
        "uq_memory_scope_key",
        "memories",
        ["room_name", "key", "scope", "owner_handle"],
    )

    # Room: is_namespace flag (true for persistent async rooms)
    op.add_column(
        "rooms",
        sa.Column("is_namespace", sa.Boolean(), server_default="false", nullable=False),
    )
    # Room: parent namespace for sessions spawned within a namespace
    op.add_column(
        "rooms",
        sa.Column("parent_namespace", sa.String(), nullable=True),
    )

    # Backfill: existing async/hybrid rooms become namespaces
    op.execute("UPDATE rooms SET is_namespace = TRUE WHERE mode IN ('async', 'hybrid')")


def downgrade() -> None:
    op.drop_column("rooms", "parent_namespace")
    op.drop_column("rooms", "is_namespace")
    op.drop_constraint("uq_memory_scope_key", "memories", type_="unique")
    op.create_unique_constraint("uq_memory_room_key", "memories", ["room_name", "key"])
    op.drop_column("memories", "owner_handle")
    op.drop_column("memories", "scope")
