from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EnvelopeSchemaLiteral = Literal["job-envelope-v1"]


class JobEnvelopeV1(BaseModel):
    """Must stay aligned with packages/contracts/json-schema/job-envelope-v1.schema.json."""

    model_config = ConfigDict(extra="forbid")

    envelope_schema_version: Annotated[
        EnvelopeSchemaLiteral,
        Field(description="Frozen contract version marker"),
    ] = "job-envelope-v1"
    job_id: str = Field(description="UUID as string")
    job_kind: Literal["train", "edit", "cull"]
    attempt: Annotated[int, Field(ge=0)] = 0
    trace_context: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(
        ...,
        description="Original HTTP body (validated prior to enqueue at API boundary)",
    )

    def dumps(self) -> str:
        return self.model_dump_json()

    @classmethod
    def loads(cls, raw: str | bytes) -> JobEnvelopeV1:
        data = raw if isinstance(raw, str) else raw.decode()
        return cls.model_validate_json(data)


def dumps_dlq_item(*, envelope_raw: str, reason: str) -> str:
    return json.dumps({"reason": reason, "envelope": json.loads(envelope_raw)})
