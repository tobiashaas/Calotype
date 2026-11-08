from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tarsier_persistence.models import EditResult


class EditResultRepository:
    @staticmethod
    def get_by_job_id(session: Session, job_id: uuid.UUID) -> EditResult | None:
        stmt = select(EditResult).where(EditResult.job_id == job_id)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_all_by_job_id(session: Session, job_id: uuid.UUID) -> list[EditResult]:
        stmt = select(EditResult).where(EditResult.job_id == job_id)
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def create(
        session: Session,
        *,
        result_id: uuid.UUID,
        job_id: uuid.UUID,
        photo_id: uuid.UUID,
        profile_id: uuid.UUID,
        lr_settings: dict[str, Any],
        s3_key: str | None = None,
    ) -> EditResult:
        result = EditResult(
            id=result_id,
            job_id=job_id,
            photo_id=photo_id,
            profile_id=profile_id,
            lr_settings=lr_settings,
            s3_key=s3_key,
        )
        session.add(result)
        session.flush()
        return result

    @staticmethod
    def upsert(
        session: Session,
        *,
        result_id: uuid.UUID,
        job_id: uuid.UUID,
        photo_id: uuid.UUID,
        profile_id: uuid.UUID,
        lr_settings: dict[str, Any],
        s3_key: str | None = None,
    ) -> None:
        """Write the result of a photo in a job; a re-run of the job replaces it."""
        stmt = insert(EditResult).values(
            id=result_id, job_id=job_id, photo_id=photo_id, profile_id=profile_id,
            lr_settings=lr_settings, s3_key=s3_key,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_edit_results_job_photo",
            set_={"lr_settings": stmt.excluded.lr_settings, "profile_id": stmt.excluded.profile_id,
                  "s3_key": stmt.excluded.s3_key},
        )
        session.execute(stmt)
