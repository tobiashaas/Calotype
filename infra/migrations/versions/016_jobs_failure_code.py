"""Failure code: a failed job says why as a code (``no_examples``, ``profile_not_ready`` …)
next to its text reason, so clients branch on the code instead of matching the text."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "016_jobs_failure_code"
down_revision = "015_edit_results_kept_crop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("failure_code", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "failure_code")
