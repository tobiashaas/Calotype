"""Job requests / queue payloads: one definition per field, read by the API and the workers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from calotype_queue.payloads import (
    CullJobRequestV1,
    CullPayloadV1,
    EditJobRequestV1,
    EditPayloadV1,
    TrainJobRequestV1,
    TrainPayloadV1,
)

CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "json-schema"
PHOTO = str(uuid.uuid4())


@pytest.mark.parametrize("model, schema_file", [
    (TrainJobRequestV1, "job-train-request-v1.schema.json"),
    (EditJobRequestV1, "job-edit-request-v1.schema.json"),
    (CullJobRequestV1, "job-cull-request-v1.schema.json"),
])
def test_json_schema_lists_the_fields_of_the_request_model(model, schema_file):
    """The contract and the model the API validates with must not drift apart (the Bridge test
    `every_server_request_field_passes_through_the_bridge` checks the contract's fields reach
    the server)."""
    schema = json.loads((CONTRACTS / schema_file).read_text(encoding="utf-8"))
    assert set(schema["properties"]) == set(model.model_fields)
    required = {name for name, field in model.model_fields.items() if field.is_required()}
    assert set(schema["required"]) == required


def test_edit_needs_a_profile_or_the_selections_edits():
    base = {"schema_version": "edit-request-v1", "photo_ids": [PHOTO]}
    with pytest.raises(ValidationError, match="learn_from_edits and format_type"):
        EditPayloadV1.model_validate(base)
    with pytest.raises(ValidationError, match="learn_from_edits and format_type"):
        EditPayloadV1.model_validate({**base, "learn_from_edits": True})
    own = EditPayloadV1.model_validate({**base, "learn_from_edits": True, "format_type": "raw"})
    assert own.profile_id is None
    assert EditPayloadV1.model_validate({**base, "profile_id": str(uuid.uuid4())}).learn_from_edits is False


def test_payload_round_trips_through_the_queue_and_ignores_unknown_fields():
    request = EditJobRequestV1.model_validate({
        "schema_version": "edit-request-v1", "photo_ids": [PHOTO], "profile_id": str(uuid.uuid4()),
        "consistent_series": True, "straighten": True, "from_a_newer_client": 1,
    })
    payload = request.model_dump(mode="json")
    assert "from_a_newer_client" not in payload
    read = EditPayloadV1.model_validate({**payload, "from_a_newer_api": "x"})
    assert read == request
    assert (read.consistent_series, read.straighten, read.photo_ids) == (True, True, [uuid.UUID(PHOTO)])


def test_train_payload_is_the_request_as_the_api_completed_it():
    request = TrainJobRequestV1.model_validate({
        "schema_version": "train-request-v1", "profile_name": "Wedding", "genre": "wedding",
        "format_type": "raw", "color_type": "color", "photo_ids": [PHOTO],
        "untouched": {"Highlights2012": -100},
    })
    payload = TrainPayloadV1.model_validate(request.model_dump()).model_dump(mode="json")
    assert payload["retrain"] is False and payload["untouched"] == {"Highlights2012": -100}
    # An earlier API wrote no "retrain" key for a first training.
    del payload["retrain"]
    assert TrainPayloadV1.model_validate(payload).retrain is False


def test_cull_payload_reads_the_photos():
    read = CullPayloadV1.model_validate({"schema_version": "cull-request-v1", "photo_ids": [PHOTO]})
    assert read.photo_ids == [uuid.UUID(PHOTO)]
