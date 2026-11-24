"""Job requests and the queue payloads made from them — one definition per field.

The API validates a request body with these models and enqueues ``model_dump(mode="json")``
as the envelope's ``payload``; the workers read that payload back through the same models
(``TrainPayloadV1.model_validate(envelope.payload)``). So a field is declared once, here, and
the API and the workers cannot drift apart. Must stay aligned with
``packages/contracts/json-schema/job-*-request-v1.schema.json`` (a test checks it).

Tolerant reader: unknown fields are ignored (and logged), not rejected — a newer Bridge must
work with an older server, and an older worker with a newer API. New *required* fields need a
new schema version.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

log = logging.getLogger("calotype.queue.payloads")

FormatType = Literal["raw", "jpeg_tiff"]


class TolerantModel(BaseModel):
    """Unknown fields are ignored (and logged); known fields keep their strict types."""

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _log_unknown(cls, data: Any) -> Any:
        if isinstance(data, dict):
            unknown = sorted(set(data) - set(cls.model_fields))
            if unknown:
                log.warning("%s: ignoring unknown fields %s", cls.__name__, unknown)
        return data


class TrainJobRequestV1(TolerantModel):
    """Train a profile from the photographer's edited photos (``train-request-v1``)."""

    schema_version: Literal["train-request-v1"]
    correlation_id: str | None = None
    profile_name: str
    genre: str
    format_type: FormatType
    color_type: Literal["color", "bw"]
    photo_ids: Annotated[list[UUID], Field(min_length=1)]
    base_preset: dict[str, Any] | None = None
    # Retrain this profile instead of creating one: its earlier training photos (with their
    # current settings) and these photos together; the profile keeps its id and stays usable.
    profile_id: UUID | None = None
    # Values only a preset left on the photos (Lightroom key → value), not the photographer's
    # decision: such a slider is left out of that photo's training target.
    untouched: dict[str, float] | None = None


class TrainPayloadV1(TrainJobRequestV1):
    """What the train worker reads: the request as the API completed it — ``profile_id``
    always set (a new profile's id too), ``photo_ids`` / ``untouched`` merged with the
    profile's earlier training, and ``retrain`` when the profile already has a model (a
    failure must not take that model away)."""

    retrain: bool = False


class EditJobRequestV1(TolerantModel):
    """Edit photos with a profile, or — without one — with the look of the selection's
    edited photos (``edit-request-v1``)."""

    schema_version: Literal["edit-request-v1"]
    correlation_id: str | None = None
    # Without a profile the look comes only from the selection's edited photos: then
    # learn_from_edits must be on and format_type says how to read white balance.
    profile_id: UUID | None = None
    format_type: FormatType | None = None
    collection_name: str | None = None
    photo_ids: Annotated[list[UUID], Field(min_length=1)]
    # Level photos that have clear reference lines (crop keys in the result).
    straighten: bool = False
    # Photos of the same scene (close in time and alike) get exposure and white balance that
    # agree; edited examples stay fixed. Needs capture times.
    consistent_series: bool = False
    # Photos of the selection the photographer already edited set the shoot's look; they are
    # examples only and get no result.
    learn_from_edits: bool = False
    # A look (develop settings of one of the photographer's presets) that replaces the
    # profile's base preset; only its look settings are used (style layer).
    base_preset: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _profile_or_edits(self) -> EditJobRequestV1:
        if self.profile_id is None and not (self.learn_from_edits and self.format_type):
            raise ValueError("without profile_id, learn_from_edits and format_type are required")
        return self


# The edit worker reads exactly what the client asked for.
EditPayloadV1 = EditJobRequestV1


class CullJobRequestV1(TolerantModel):
    """Cull these photos. Photos among them that already carry a decision (stars, pick/reject
    flag) teach the scorer the photographer's taste (``cull-request-v1``)."""

    schema_version: Literal["cull-request-v1"]
    correlation_id: str | None = None
    photo_ids: Annotated[list[UUID], Field(min_length=1)]


CullPayloadV1 = CullJobRequestV1
