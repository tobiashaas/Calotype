"""Tests for job endpoints."""

from __future__ import annotations

import uuid

_PHOTO_ID = str(uuid.uuid4())


def _train_body(**overrides) -> dict:
    return {
        "schema_version": "train-request-v1",
        "profile_name": "Golden Hour",
        "genre": "landscape",
        "format_type": "raw",
        "color_type": "color",
        "photo_ids": [_PHOTO_ID],
        "base_preset": {"exposure": 0.3},
        **overrides,
    }


def test_create_train_job_returns_202(client, mock_publisher):
    resp = client.post("/v1/jobs/train", json=_train_body())
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "train"
    assert "job_id" in body
    mock_publisher.enqueue.assert_called_once()


def test_create_train_job_idempotency(client):
    key = "idem-train-001"
    r1 = client.post("/v1/jobs/train", json=_train_body(), headers={"Idempotency-Key": key})
    r2 = client.post("/v1/jobs/train", json=_train_body(), headers={"Idempotency-Key": key})
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_get_job_not_found(client):
    resp = client.get(f"/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_job_result_not_found(client):
    resp = client.get(f"/v1/jobs/{uuid.uuid4()}/result")
    assert resp.status_code == 404


def test_create_edit_job_unknown_profile(client):
    body = {
        "schema_version": "edit-request-v1",
        "profile_id": str(uuid.uuid4()),
        "photo_ids": [str(uuid.uuid4())],
    }
    resp = client.post("/v1/jobs/edit", json=body)
    assert resp.status_code == 422
    assert "profile not found" in resp.json()["detail"]


def test_get_job_after_train(client):
    r = client.post("/v1/jobs/train", json=_train_body())
    job_id = r.json()["job_id"]
    resp = client.get(f"/v1/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_train_job_exposes_profile_id(client):
    accepted = client.post("/v1/jobs/train", json=_train_body()).json()
    assert accepted["profile_id"]
    snapshot = client.get(f"/v1/jobs/{accepted['job_id']}").json()
    assert snapshot["profile_id"] == accepted["profile_id"]
    assert snapshot["failure_reason"] is None
    profile = client.get(f"/v1/profiles/{accepted['profile_id']}")
    assert profile.status_code == 200


def test_get_job_result_not_completed(client):
    r = client.post("/v1/jobs/train", json=_train_body())
    job_id = r.json()["job_id"]
    resp = client.get(f"/v1/jobs/{job_id}/result")
    assert resp.status_code == 409


def test_list_profiles_empty(client):
    resp = client.get("/v1/profiles")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_profile_not_found(client):
    resp = client.get(f"/v1/profiles/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_list_profiles_after_train_job(client):
    client.post("/v1/jobs/train", json=_train_body())
    resp = client.get("/v1/profiles")
    assert resp.status_code == 200
    profiles = resp.json()
    assert len(profiles) == 1
    assert profiles[0]["status"] == "draft"


def _upload(client) -> str:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG")
    meta = {"schema_version": "photo-upload-v1", "lr_catalog_uuid": str(uuid.uuid4()),
            "lr_metadata": {"rating": 5}}
    import json

    r = client.post("/v1/photos", files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")},
                    data={"metadata": json.dumps(meta)})
    return r.json()["photo_id"]


def test_cull_job_is_queued_and_result_waits_for_completion(client, mock_publisher):
    pid = _upload(client)
    r = client.post("/v1/jobs/cull", json={"schema_version": "cull-request-v1", "photo_ids": [pid]})
    assert r.status_code == 202 and r.json()["kind"] == "cull"
    assert mock_publisher.enqueue.call_args[0][0].job_kind == "cull"
    res = client.get(f"/v1/jobs/{r.json()['job_id']}/cull-result")
    assert res.status_code == 409


def test_cull_job_rejects_unknown_photos(client):
    r = client.post("/v1/jobs/cull", json={"schema_version": "cull-request-v1", "photo_ids": [str(uuid.uuid4())]})
    assert r.status_code == 422 and "unknown photo_ids" in r.json()["detail"]
