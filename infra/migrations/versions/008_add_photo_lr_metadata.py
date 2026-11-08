"""Add photos.lr_metadata (rating, pick/reject flag, color label) for culling labels."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "008_photo_lr_metadata"
down_revision = "007_vector_dim_128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "photos",
        sa.Column("lr_metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("photos", "lr_metadata")
