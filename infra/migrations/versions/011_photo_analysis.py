"""photos.analysis: preview analysis computed once by the feature worker (e.g. straighten)."""

from __future__ import annotations

from alembic import op

revision = "011_photo_analysis"
down_revision = "010_job_progress_unique_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE photos ADD COLUMN analysis JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE photos DROP COLUMN analysis")
