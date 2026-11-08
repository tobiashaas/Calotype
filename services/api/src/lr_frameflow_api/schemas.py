"""Pydantic request/response models aligned with packages/contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

log = logging.getLogger("lr_ff.api.schemas")

TrainSchema = Literal["train-request-v1"]
EditSchema = Literal["edit-request-v1"]
CullSchema = Literal["cull-request-v1"]
PhotoSchema = Literal["photo-upload-v1"]


class TolerantRequest(BaseModel):
    """Tolerant reader: unknown *optional* fields are ignored (and logged), not rejected.

    A newer Bridge may send fields this server does not know yet; refusing them would break
    every upload after a client update. New *required* fields still need a new schema
    version. Known fields keep their strict types.
    """

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _log_unknown(cls, data: Any) -> Any:
        if isinstance(data, dict):
            unknown = sorted(set(data) - set(cls.model_fields))
            if unknown:
                log.warning("%s: ignoring unknown fields %s", cls.__name__, unknown)
        return data


class TrainJobRequestV1(TolerantRequest):

    schema_version: TrainSchema
    correlation_id: str | None = None
    profile_name: str
    genre: str
    format_type: Literal["raw", "jpeg_tiff"]
    color_type: Literal["color", "bw"]
    photo_ids: Annotated[list[UUID], Field(min_length=1)]
    base_preset: dict[str, Any] | None = None


class EditJobRequestV1(TolerantRequest):

    schema_version: EditSchema
    correlation_id: str | None = None
    profile_id: UUID
    collection_name: str | None = None
    photo_ids: Annotated[list[UUID], Field(min_length=1)]
    # Optional: level photos that have clear reference lines (crop keys in the result).
    straighten: bool = False


class CullJobRequestV1(TolerantRequest):
    """Cull these photos. Photos among them that already carry a decision (stars, pick/reject
    flag) teach the scorer the photographer's taste."""

    schema_version: CullSchema
    correlation_id: str | None = None
    photo_ids: Annotated[list[UUID], Field(min_length=1)]


class PhotoMetadataV1(TolerantRequest):

    schema_version: PhotoSchema
    lr_catalog_uuid: str
    exif_snapshot: dict[str, Any] = Field(default_factory=dict)
    lr_develop_settings: dict[str, Any] = Field(default_factory=dict)
    # Rating, pick/reject flag, color label: culling labels (ADR 005).
    lr_metadata: dict[str, Any] = Field(default_factory=dict)


class JobAcceptedResponse(BaseModel):
    job_id: UUID
    status: Literal["queued"] = "queued"
    kind: Literal["train", "edit", "cull"]
    profile_id: UUID | None = None


class JobSnapshotResponse(BaseModel):
    job_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    payload_schema_version: str | None = None
    profile_id: UUID | None = None
    failure_reason: str | None = None
    correlation_id: str | None = None


class PhotoCreatedResponse(BaseModel):
    photo_id: UUID
    s3_key: str
    already_existed: bool


class ProfileResponse(BaseModel):
    profile_id: UUID
    name: str
    genre: str
    format_type: str
    color_type: str
    status: str
    version: int
    model_artifact_key: str | None = None
    failure_reason: str | None = None


class CullResultResponse(BaseModel):
    job_id: UUID
    photo_id: UUID
    bucket: Literal["keep", "uncertain", "reject"]
    score: float
    reason: str
    method: Literal["learned", "rules"]


class EditResultResponse(BaseModel):
    job_id: UUID
    photo_id: UUID
    lr_settings: dict[str, Any]
    s3_key: str | None = None
