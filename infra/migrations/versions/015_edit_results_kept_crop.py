"""Kept crop: an edit result that was straightened, but whose photo already had a crop of its
own, says so — the server decides that rule now, the plugin only counts it."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015_edit_results_kept_crop"
down_revision = "014_learned_mask_strengths"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("edit_results", sa.Column("kept_crop", sa.Boolean, nullable=True))


def downgrade() -> None:
    op.drop_column("edit_results", "kept_crop")
