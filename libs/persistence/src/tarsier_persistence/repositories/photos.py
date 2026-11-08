from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tarsier_persistence.models import Photo


class PhotoRepository:
    @staticmethod
    def get_by_id(session: Session, photo_id: uuid.UUID) -> Photo | None:
        return session.get(Photo, photo_id)

    @staticmethod
    def get_by_lr_catalog_uuid(session: Session, lr_catalog_uuid: str) -> Photo | None:
        stmt = select(Photo).where(Photo.lr_catalog_uuid == lr_catalog_uuid)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def set_feature_vector_id(
        session: Session, photo_id: uuid.UUID, feature_vector_id: uuid.UUID
    ) -> None:
        photo = session.get(Photo, photo_id)
        if photo is not None:
            photo.feature_vector_id = feature_vector_id
            session.flush()

    @staticmethod
    def merge_analysis(session: Session, photo_id: uuid.UUID, analysis: dict) -> None:
        """Add keys to the photo's analysis (existing keys are replaced)."""
        photo = session.get(Photo, photo_id)
        if photo is not None:
            photo.analysis = {**(photo.analysis or {}), **analysis}
            session.flush()

    @staticmethod
    def create(
        session: Session,
        *,
        photo_id: uuid.UUID,
        lr_catalog_uuid: str,
        s3_key: str,
        exif_snapshot: dict[str, Any],
        lr_develop_settings: dict[str, Any],
        lr_metadata: dict[str, Any] | None = None,
    ) -> Photo:
        photo = Photo(
            id=photo_id,
            lr_catalog_uuid=lr_catalog_uuid,
            s3_key=s3_key,
            exif_snapshot=exif_snapshot,
            lr_develop_settings=lr_develop_settings,
            lr_metadata=lr_metadata or {},
        )
        session.add(photo)
        session.flush()
        return photo

    @staticmethod
    def refresh(
        session: Session,
        photo: Photo,
        *,
        exif_snapshot: dict[str, Any],
        lr_develop_settings: dict[str, Any],
        lr_metadata: dict[str, Any],
    ) -> Photo:
        """Re-upload of a known photo: the preview stays, edits and decisions are current."""
        photo.exif_snapshot = exif_snapshot
        photo.lr_develop_settings = lr_develop_settings
        photo.lr_metadata = lr_metadata
        session.flush()
        return photo
