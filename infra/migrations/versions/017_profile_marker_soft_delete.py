"""One living profile: the photographer's marker for accepted photos and soft delete.

``accepted_marker`` (JSON, null = none): how the photographer marks photos they reviewed after
Calotype applied the profile and left unchanged — ``{"kind": "label", "value": "green"}`` or
``{"kind": "rating", "min": 4}``. The next retrain dialog preselects it.

``deleted_at``: a deleted profile is only hidden (list, apply, retrain); its rows, jobs, edit
results and model artifacts in S3 stay.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "017_profile_marker_soft_delete"
down_revision = "016_jobs_failure_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("accepted_marker", postgresql.JSONB(), nullable=True))
    op.add_column("profiles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "deleted_at")
    op.drop_column("profiles", "accepted_marker")
