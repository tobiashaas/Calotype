from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tarsier_domain.profiles import ProfileStatus
from tarsier_persistence.models import Profile


class ProfileRepository:
    @staticmethod
    def get_by_id(session: Session, profile_id: uuid.UUID) -> Profile | None:
        return session.get(Profile, profile_id)

    @staticmethod
    def list_all(session: Session) -> list[Profile]:
        stmt = select(Profile).order_by(Profile.created_at.desc())
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def create(
        session: Session,
        *,
        profile_id: uuid.UUID,
        name: str,
        genre: str,
        format_type: str,
        color_type: str,
        base_preset: dict[str, Any] | None,
    ) -> Profile:
        profile = Profile(
            id=profile_id,
            name=name,
            genre=genre,
            format_type=format_type,
            color_type=color_type,
            status=ProfileStatus.DRAFT.value,
            base_preset=base_preset,
        )
        session.add(profile)
        session.flush()
        return profile

    @staticmethod
    def set_status(
        session: Session,
        profile_id: uuid.UUID,
        status: ProfileStatus,
        *,
        failure_reason: str | None = None,
    ) -> Profile | None:
        profile = session.get(Profile, profile_id)
        if profile is None:
            return None
        profile.sync_status_enum(status)
        profile.failure_reason = failure_reason
        session.flush()
        return profile

    @staticmethod
    def set_artifact(
        session: Session,
        profile_id: uuid.UUID,
        *,
        model_artifact_key: str,
        lr_output_keys: list[str] | None = None,
    ) -> Profile | None:
        profile = session.get(Profile, profile_id)
        if profile is None:
            return None
        profile.model_artifact_key = model_artifact_key
        if lr_output_keys is not None:
            profile.lr_output_keys = lr_output_keys
        session.flush()
        return profile
