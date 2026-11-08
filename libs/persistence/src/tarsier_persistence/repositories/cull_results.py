from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tarsier_persistence.models import CullResult


class CullResultRepository:
    @staticmethod
    def get_all_by_job_id(session: Session, job_id: uuid.UUID) -> list[CullResult]:
        return list(session.execute(select(CullResult).where(CullResult.job_id == job_id)).scalars().all())

    @staticmethod
    def upsert(session: Session, *, job_id: uuid.UUID, photo_id: uuid.UUID, bucket: str, score: float,
               reason: str, method: str) -> None:
        """One decision per photo and job; a re-run replaces it."""
        stmt = insert(CullResult).values(id=uuid.uuid4(), job_id=job_id, photo_id=photo_id, bucket=bucket,
                                         score=score, reason=reason[:1024], method=method)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_cull_results_job_photo",
            set_={"bucket": stmt.excluded.bucket, "score": stmt.excluded.score,
                  "reason": stmt.excluded.reason, "method": stmt.excluded.method},
        )
        session.execute(stmt)
