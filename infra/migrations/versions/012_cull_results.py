"""cull_results: culling decision (bucket, score, reason) per photo and cull job."""

from __future__ import annotations

from alembic import op

revision = "012_cull_results"
down_revision = "011_photo_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cull_results (
            id UUID PRIMARY KEY,
            job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            photo_id UUID NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            bucket VARCHAR(16) NOT NULL,
            score DOUBLE PRECISION NOT NULL,
            reason VARCHAR(1024) NOT NULL DEFAULT '',
            method VARCHAR(16) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cull_results_job_photo UNIQUE (job_id, photo_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE cull_results")
