# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Add participants.context_files JSONB.

Stores files an agent explicitly opted into sharing with the session at join
time as ``[{"path": str, "content": str, "sha256": str}]``. Content is
included because this is opt-in shared context — the same data flows to
other participants via ticks and to KXP/CFN as a deliberate room write.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("participants") as batch:
        batch.add_column(
            sa.Column(
                "context_files",
                JSONB().with_variant(sa.JSON(), "sqlite"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("participants") as batch:
        batch.drop_column("context_files")
