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
    assert snapshot["failure_reason"] is None and snapshot["failure_code"] is None
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


def test_edit_job_without_profile_needs_learning_and_format(client):
    base = {"schema_version": "edit-request-v1", "photo_ids": [str(uuid.uuid4())]}
    assert client.post("/v1/jobs/edit", json=base).status_code == 422
    assert client.post("/v1/jobs/edit", json={**base, "learn_from_edits": True}).status_code == 422


def test_edit_job_without_profile_learns_from_edits(client, mock_publisher):
    photo_id = _upload(client)
    body = {"schema_version": "edit-request-v1", "photo_ids": [photo_id],
            "learn_from_edits": True, "format_type": "raw"}
    resp = client.post("/v1/jobs/edit", json=body)
    assert resp.status_code == 202
    payload = mock_publisher.enqueue.call_args[0][0].payload
    assert payload["profile_id"] is None and payload["format_type"] == "raw"


def test_edit_job_carries_a_chosen_look(client, mock_publisher):
    photo_id = _upload(client)
    body = {"schema_version": "edit-request-v1", "photo_ids": [photo_id], "learn_from_edits": True,
            "format_type": "raw", "base_preset": {"GrainAmount": 25, "ToneCurvePV2012": [0, 12, 255, 240]}}
    assert client.post("/v1/jobs/edit", json=body).status_code == 202
    payload = mock_publisher.enqueue.call_args[0][0].payload
    assert payload["base_preset"]["GrainAmount"] == 25


def test_retraining_keeps_the_profile_and_learns_from_all_its_photos(client, store, mock_publisher):
    """One living profile: a retrain adds new photos to the earlier ones under the same id."""
    first = client.post("/v1/jobs/train", json=_train_body(untouched={"Highlights2012": -100})).json()
    profile_id = first["profile_id"]
    store.profiles.get(uuid.UUID(profile_id)).model_artifact_key = f"models/{profile_id}/model.joblib"
    new_photo = str(uuid.uuid4())

    resp = client.post("/v1/jobs/train", json=_train_body(profile_id=profile_id, photo_ids=[new_photo, _PHOTO_ID]))

    assert resp.status_code == 202
    assert resp.json()["profile_id"] == profile_id
    assert len(store.profiles.list_all()) == 1
    payload = mock_publisher.enqueue.call_args.args[0].payload
    assert payload["photo_ids"] == [_PHOTO_ID, new_photo]       # earlier photos first, each once
    assert payload["untouched"] == {"Highlights2012": -100}      # placeholders carry over
    assert payload["retrain"] is True


def test_retraining_an_unknown_profile_is_404(client):
    resp = client.post("/v1/jobs/train", json=_train_body(profile_id=str(uuid.uuid4())))
    assert resp.status_code == 404


def test_retraining_with_another_format_is_409(client):
    profile_id = client.post("/v1/jobs/train", json=_train_body()).json()["profile_id"]
    resp = client.post("/v1/jobs/train", json=_train_body(profile_id=profile_id, format_type="jpeg_tiff"))
    assert resp.status_code == 409


def test_completed_edit_job_returns_each_photos_settings_and_masks(client, store):
    photo_id = _upload(client)
    body = {"schema_version": "edit-request-v1", "photo_ids": [photo_id],
            "learn_from_edits": True, "format_type": "raw"}
    job_id = client.post("/v1/jobs/edit", json=body).json()["job_id"]
    job = store.jobs.get(uuid.UUID(job_id))
    store.edit_results.upsert(result_id=uuid.uuid4(), job_id=job.id, photo_id=uuid.UUID(photo_id),
                              profile_id=None, lr_settings={"Exposure2012": 0.4},
                              retouch={"subject_pop": {"LocalExposure2012": 0.2}})
    job.status = "completed"

    resp = client.get(f"/v1/jobs/{job_id}/result")

    assert resp.status_code == 200
    [result] = resp.json()
    assert result["photo_id"] == photo_id
    assert result["lr_settings"] == {"Exposure2012": 0.4}
    assert result["retouch"] == {"subject_pop": {"LocalExposure2012": 0.2}}


def test_completed_cull_job_returns_a_decision_per_photo(client, store):
    photo_id = _upload(client)
    job_id = client.post("/v1/jobs/cull", json={"schema_version": "cull-request-v1",
                                                 "photo_ids": [photo_id]}).json()["job_id"]
    job = store.jobs.get(uuid.UUID(job_id))
    store.cull_results.upsert(job_id=job.id, photo_id=uuid.UUID(photo_id), bucket="keep", score=0.9,
                              reason="sharp, eyes open", method="rules")
    job.status = "completed"

    resp = client.get(f"/v1/jobs/{job_id}/cull-result")

    assert resp.status_code == 200
    assert [(r["photo_id"], r["bucket"], r["method"]) for r in resp.json()] == [(photo_id, "keep", "rules")]


def test_cull_result_of_an_edit_job_is_409(client):
    photo_id = _upload(client)
    body = {"schema_version": "edit-request-v1", "photo_ids": [photo_id],
            "learn_from_edits": True, "format_type": "raw"}
    job_id = client.post("/v1/jobs/edit", json=body).json()["job_id"]
    assert client.get(f"/v1/jobs/{job_id}/cull-result").status_code == 409


def test_failed_job_snapshot_carries_its_failure_code(client, store):
    photo_id = _upload(client)
    body = {"schema_version": "edit-request-v1", "photo_ids": [photo_id],
            "learn_from_edits": True, "format_type": "raw"}
    job_id = client.post("/v1/jobs/edit", json=body).json()["job_id"]
    job = store.jobs.get(uuid.UUID(job_id))
    job.status, job.failure_reason, job.failure_code = "failed", "NoExamplesError: no edited photos", "no_examples"

    snapshot = client.get(f"/v1/jobs/{job_id}").json()

    assert (snapshot["status"], snapshot["failure_code"]) == ("failed", "no_examples")


def test_first_training_payload_names_its_new_profile(client, mock_publisher):
    accepted = client.post("/v1/jobs/train", json=_train_body()).json()
    payload = mock_publisher.enqueue.call_args.args[0].payload
    assert payload["profile_id"] == accepted["profile_id"] and payload["retrain"] is False
