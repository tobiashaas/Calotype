"""Add profile_id and started_at to jobs table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_extend_jobs"
down_revision = "005_create_edit_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_jobs_profile_id",
        "jobs",
        "profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_profile_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "profile_id")
