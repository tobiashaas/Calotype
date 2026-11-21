"""Create photos table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_create_photos"
down_revision = "001_create_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lr_catalog_uuid", sa.String(length=256), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column(
            "exif_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "lr_develop_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("feature_vector_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_photos_lr_catalog_uuid", "photos", ["lr_catalog_uuid"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_photos_lr_catalog_uuid", table_name="photos")
    op.drop_table("photos")
