"""Learned mask strengths: per kind of AI mask (subject, sky …) the local values the photographer
uses — on a profile (from its training photos) and on each edit result (applied by the plugin)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "014_learned_mask_strengths"
down_revision = "013_edit_results_without_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("retouch", JSONB, nullable=True))
    op.add_column("edit_results", sa.Column("retouch", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("edit_results", "retouch")
    op.drop_column("profiles", "retouch")
