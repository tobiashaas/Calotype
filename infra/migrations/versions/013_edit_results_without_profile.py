"""edit_results.profile_id nullable: an edit job may learn the look from the selection's edited
photos alone, without a profile."""

from __future__ import annotations

from alembic import op

revision = "013_edit_results_without_profile"
down_revision = "012_cull_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("edit_results", "profile_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM edit_results WHERE profile_id IS NULL")
    op.alter_column("edit_results", "profile_id", nullable=False)
