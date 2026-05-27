# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Drop notebook scope from memories.

Removes the scope/owner_handle columns and the (room, key, scope, owner)
unique constraint, replacing it with a (room, key) constraint. Notebook-scoped
rows are dropped — agents now use their native private memory instead of a
Mycelium-managed parallel store.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM memories WHERE scope = 'notebook'")
    op.drop_constraint("uq_memory_scope_key", "memories", type_="unique")
    op.create_unique_constraint("uq_memory_room_key", "memories", ["room_name", "key"])
    op.drop_column("memories", "owner_handle")
    op.drop_column("memories", "scope")


def downgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("scope", sa.VARCHAR(20), server_default="namespace", nullable=False),
    )
    op.add_column(
        "memories",
        sa.Column("owner_handle", sa.String(), nullable=True, index=True),
    )
    op.drop_constraint("uq_memory_room_key", "memories", type_="unique")
    op.create_unique_constraint(
        "uq_memory_scope_key",
        "memories",
        ["room_name", "key", "scope", "owner_handle"],
    )
