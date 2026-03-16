"""Add coordination fields to rooms and sessions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── rooms: coordination state machine ─────────────────────────────────────
    op.add_column(
        "rooms",
        sa.Column(
            "coordination_state",
            sa.VARCHAR(20),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "rooms",
        sa.Column("join_deadline", sa.DateTime(timezone=True), nullable=True),
    )

    # ── sessions: agent intent ─────────────────────────────────────────────────
    op.add_column(
        "sessions",
        sa.Column("intent", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "intent")
    op.drop_column("rooms", "join_deadline")
    op.drop_column("rooms", "coordination_state")
