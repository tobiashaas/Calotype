"""Job progress and one edit result per photo and job.

- jobs.last_progress_at: workers touch it per photo; the reaper only takes jobs without
  progress for stuck (before, any job running longer than 10 minutes was re-run).
- edit_results UNIQUE (job_id, photo_id): a re-run replaces results instead of adding
  them (a 100-photo job had returned 300 results).
"""

from __future__ import annotations

from alembic import op

revision = "010_job_progress_unique_results"
down_revision = "009_versioned_feature_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN last_progress_at TIMESTAMPTZ")
    # Keep the newest result of each photo in a job, drop the duplicates of earlier re-runs.
    op.execute(
        "DELETE FROM edit_results a USING edit_results b "
        "WHERE a.job_id = b.job_id AND a.photo_id = b.photo_id "
        "AND (a.created_at, a.id::text) < (b.created_at, b.id::text)"
    )
    op.execute(
        "ALTER TABLE edit_results ADD CONSTRAINT uq_edit_results_job_photo UNIQUE (job_id, photo_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE edit_results DROP CONSTRAINT uq_edit_results_job_photo")
    op.execute("ALTER TABLE jobs DROP COLUMN last_progress_at")
