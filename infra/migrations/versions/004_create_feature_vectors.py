"""Create feature_vectors table (pgvector)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_create_feature_vectors"
down_revision = "003_create_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard: extension is created by postgres-init script, but ensure it exists.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create table with vector(200) column via raw DDL — pgvector type not available in sa types.
    op.execute("""
        CREATE TABLE feature_vectors (
            id          UUID        NOT NULL,
            photo_id    UUID        NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            model_version VARCHAR(64) NOT NULL,
            vector      vector(200) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            CONSTRAINT uq_feature_vectors_photo_id UNIQUE (photo_id)
        )
    """)


def downgrade() -> None:
    op.drop_table("feature_vectors")
