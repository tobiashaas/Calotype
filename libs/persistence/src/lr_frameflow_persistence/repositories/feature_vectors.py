from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from lr_frameflow_persistence.models import FeatureVector


class FeatureVectorRepository:
    @staticmethod
    def get_by_photo_id(
        session: Session, photo_id: uuid.UUID, model_version: str | None = None
    ) -> FeatureVector | None:
        """The photo's vector of a feature version (newest of any version if None)."""
        stmt = select(FeatureVector).where(FeatureVector.photo_id == photo_id)
        if model_version is not None:
            stmt = stmt.where(FeatureVector.model_version == model_version)
        stmt = stmt.order_by(FeatureVector.created_at.desc()).limit(1)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create(
        session: Session,
        *,
        vector_id: uuid.UUID,
        photo_id: uuid.UUID,
        model_version: str,
        vector: list[float],
    ) -> FeatureVector:
        fv = FeatureVector(
            id=vector_id,
            photo_id=photo_id,
            model_version=model_version,
            vector=vector,
        )
        session.add(fv)
        session.flush()
        return fv
