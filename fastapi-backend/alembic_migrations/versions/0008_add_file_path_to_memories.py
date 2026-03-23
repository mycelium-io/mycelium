"""Add file_path column to memories for filesystem-native storage.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("file_path", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "file_path")
