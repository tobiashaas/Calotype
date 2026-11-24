"""Pydantic request/response models aligned with packages/contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# The job requests live with the queue payloads (one definition per field, read by the
# workers too); re-exported here as the API's request models.
from calotype_queue.payloads import CullJobRequestV1 as CullJobRequestV1
from calotype_queue.payloads import EditJobRequestV1 as EditJobRequestV1
from calotype_queue.payloads import TolerantModel as TolerantRequest
from calotype_queue.payloads import TrainJobRequestV1 as TrainJobRequestV1

PhotoSchema = Literal["photo-upload-v1"]


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
    # Why it failed as a code (calotype_domain.FailureCode): clients branch on it, not on text.
    failure_code: str | None = None
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
    # Learned mask strengths: AI masks to add with these local values ({retouch id: {key: value}}).
    retouch: dict[str, dict[str, float]] | None = None
    # Straightened, but the photo has a crop of its own: it keeps it (no crop keys above).
    kept_crop: bool | None = None
