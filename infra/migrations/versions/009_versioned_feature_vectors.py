"""One feature vector per photo *and feature version*, any length.

v1 (histogram, 128 floats) and v2 (histogram + tone/color stats + face, 153 floats) live
side by side: profiles trained on v1 keep working while new profiles use v2.
"""

from __future__ import annotations

from alembic import op

revision = "009_versioned_feature_vectors"
down_revision = "008_photo_lr_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feature_vectors DROP CONSTRAINT uq_feature_vectors_photo_id")
    op.execute(
        "ALTER TABLE feature_vectors ADD CONSTRAINT uq_feature_vectors_photo_version "
        "UNIQUE (photo_id, model_version)"
    )
    # Unconstrained pgvector column: each version has its own length.
    op.execute("ALTER TABLE feature_vectors ALTER COLUMN vector TYPE vector")


def downgrade() -> None:
    op.execute("DELETE FROM feature_vectors WHERE model_version <> 'histogram-v1'")
    op.execute("ALTER TABLE feature_vectors ALTER COLUMN vector TYPE vector(128)")
    op.execute("ALTER TABLE feature_vectors DROP CONSTRAINT uq_feature_vectors_photo_version")
    op.execute(
        "ALTER TABLE feature_vectors ADD CONSTRAINT uq_feature_vectors_photo_id UNIQUE (photo_id)"
    )
