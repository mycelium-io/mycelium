# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Add audit_events table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_identifier", sa.String(128), nullable=False),
        sa.Column("audit_type", sa.String(64), nullable=False),
        sa.Column("audit_resource_identifier", sa.String(128), nullable=False),
        sa.Column("audit_information", JSONB, nullable=True),
        sa.Column("audit_extra_information", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_modified_by", UUID(as_uuid=True), nullable=False),
        sa.Column("last_modified_on", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_resource_type", "audit_events", ["resource_type"])
    op.create_index("ix_audit_events_audit_type", "audit_events", ["audit_type"])
    op.create_index("ix_audit_events_created_on", "audit_events", ["created_on"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_on", "audit_events")
    op.drop_index("ix_audit_events_audit_type", "audit_events")
    op.drop_index("ix_audit_events_resource_type", "audit_events")
    op.drop_table("audit_events")
