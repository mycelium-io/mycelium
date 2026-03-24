"""Resize embedding vector column from 384 to 1536.

Supports pluggable embedding providers with different dimensions.
All embeddings are zero-padded to 1536 so the column never needs resizing.

Existing embeddings are cleared and rebuilt automatically on next backend
startup (incremental scan + file watcher handle this).

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AgensGraph's pgvector can't ALTER TYPE vector(N) or cast between sizes.
    # Drop and recreate. Embeddings are rebuilt on next startup scan.
    op.drop_column("memories", "embedding")
    op.add_column("memories", sa.Column("embedding", Vector(1536), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "embedding")
    op.add_column("memories", sa.Column("embedding", Vector(384), nullable=True))
