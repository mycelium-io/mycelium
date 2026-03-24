"""Resize embedding vector column from 384 to 1536.

Supports pluggable embedding providers with different dimensions.
All embeddings are zero-padded to 1536 so the column never needs resizing.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Resize the vector column: 384 → 1536
    # pgvector ALTER COLUMN ... TYPE vector(N) re-validates and zero-pads existing data.
    op.execute("ALTER TABLE memories ALTER COLUMN embedding TYPE vector(1536)")


def downgrade() -> None:
    # Truncate back to 384 (loses dimensions > 384)
    op.execute("ALTER TABLE memories ALTER COLUMN embedding TYPE vector(384)")
