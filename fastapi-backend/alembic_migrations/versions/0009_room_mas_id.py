# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Add mas_id and workspace_id to rooms for CFN MAS sync.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("mas_id", sa.String(), nullable=True))
    op.add_column("rooms", sa.Column("workspace_id", sa.String(), nullable=True))
    op.create_index("ix_rooms_mas_id", "rooms", ["mas_id"])


def downgrade() -> None:
    op.drop_index("ix_rooms_mas_id", table_name="rooms")
    op.drop_column("rooms", "workspace_id")
    op.drop_column("rooms", "mas_id")
