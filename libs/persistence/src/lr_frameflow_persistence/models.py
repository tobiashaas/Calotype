from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lr_frameflow_domain.jobs import JobKind, JobStatus
from lr_frameflow_domain.profiles import ProfileStatus


class Base(DeclarativeBase):
    pass


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    lr_catalog_uuid: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)

    exif_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=func.cast("{}", JSONB)
    )
    lr_develop_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=func.cast("{}", JSONB)
    )

    # Rating, pick/reject flag, color label from Lightroom or XMP (culling labels).
    lr_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=func.cast("{}", JSONB)
    )

    # Populated by feature worker in Phase 2; plain UUID column (no FK) to avoid circularity.
    feature_vector_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    genre: Mapped[str] = mapped_column(String(64), nullable=False)
    format_type: Mapped[str] = mapped_column(String(16), nullable=False)  # raw | jpeg_tiff
    color_type: Mapped[str] = mapped_column(String(8), nullable=False)    # color | bw
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    base_preset: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    model_artifact_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lr_output_keys: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    failure_reason: Mapped[str | None] = mapped_column(String(4096), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def sync_status_enum(self, status: ProfileStatus) -> None:
        self.status = status.value


class FeatureVector(Base):
    __tablename__ = "feature_vectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    # One vector per photo and feature version (migration 009); length depends on the version.
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("photos.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[Any] = mapped_column(Vector(), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EditResult(Base):
    __tablename__ = "edit_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("photos.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lr_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=func.cast("{}", JSONB)
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    payload_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)

    correlation_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    failure_reason: Mapped[str | None] = mapped_column(String(4096), nullable=True)

    # Added in migration 006
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def sync_kind_enum(self, kind: JobKind) -> None:
        self.kind = kind.value

    def sync_status_enum(self, status: JobStatus) -> None:
        self.status = status.value
