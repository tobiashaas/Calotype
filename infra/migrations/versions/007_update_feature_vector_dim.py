"""Change feature_vectors.vector from vector(200) to vector(128)."""

from __future__ import annotations

from alembic import op

revision = "007_vector_dim_128"
down_revision = "006_extend_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Truncate existing rows — dev/test data only, no production data at this stage
    op.execute("DELETE FROM feature_vectors")
    op.execute("ALTER TABLE feature_vectors ALTER COLUMN vector TYPE vector(128)")


def downgrade() -> None:
    op.execute("DELETE FROM feature_vectors")
    op.execute("ALTER TABLE feature_vectors ALTER COLUMN vector TYPE vector(200)")
