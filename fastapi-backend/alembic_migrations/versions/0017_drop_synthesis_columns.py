# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Drop synthesis-only columns from rooms.

The ``room synthesize`` + ``mycelium catchup`` system is removed. With it go
three columns on ``rooms`` that only existed to support it:

- ``coordination_state``  — only values were ``idle`` / ``synthesizing``;
  session state lives on ``coordination_sessions.state``, never on rooms.
- ``trigger_config``      — JSON config for the synthesis auto-trigger.
- ``last_synthesis_at``   — bookkeeping for the synthesis cache.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("last_synthesis_at")
        batch.drop_column("trigger_config")
        batch.drop_column("coordination_state")


def downgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(
            sa.Column(
                "coordination_state",
                sa.String(length=20),
                nullable=False,
                server_default="idle",
            )
        )
        batch.add_column(
            sa.Column(
                "trigger_config",
                JSONB().with_variant(sa.JSON(), "sqlite"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("last_synthesis_at", sa.DateTime(timezone=True), nullable=True))
