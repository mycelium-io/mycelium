# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Add the typed ``event`` message primitive (#392).

Four new nullable columns on ``messages``:

- ``metadata``          — full structured event metadata (kind, ttl_seconds,
                          status, payload, provenance, correlation_id),
                          returned intact to clients.
- ``event_kind``        — promoted from metadata.kind at write time.
- ``event_status``      — promoted from metadata.status; backs the ledger.
- ``event_expires_at``  — created_at + ttl_seconds, precomputed for the TTL
                          sweep. NULL = durable.

Plus the two composite indexes that keep feed (?kind=) and ledger (?status=)
queries cheap. All columns are NULL for non-event message types, so existing
rows and writers are unaffected.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(
            sa.Column(
                "metadata",
                JSONB().with_variant(sa.JSON(), "sqlite"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("event_kind", sa.String(), nullable=True))
        batch.add_column(sa.Column("event_status", sa.String(), nullable=True))
        batch.add_column(sa.Column("event_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_messages_event_expires_at", "messages", ["event_expires_at"])
    op.create_index(
        "ix_messages_room_kind_created",
        "messages",
        ["room_name", "event_kind", "created_at"],
    )
    op.create_index(
        "ix_messages_room_kind_status",
        "messages",
        ["room_name", "event_kind", "event_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_room_kind_status", table_name="messages")
    op.drop_index("ix_messages_room_kind_created", table_name="messages")
    op.drop_index("ix_messages_event_expires_at", table_name="messages")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("event_expires_at")
        batch.drop_column("event_status")
        batch.drop_column("event_kind")
        batch.drop_column("metadata")
