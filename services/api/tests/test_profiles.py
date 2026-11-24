"""One living profile: the photographer's marker for accepted photos, rename, delete."""

from __future__ import annotations

import uuid

from calotype_domain.profiles import ProfileStatus


def _photo(store, lr_uuid: str):
    return store.photos.create(photo_id=uuid.uuid4(), lr_catalog_uuid=lr_uuid, s3_key=f"photos/{lr_uuid}.jpg",
                               exif_snapshot={}, lr_develop_settings={"Exposure2012": 0.3})


def _train(client, photos, **overrides):
    body = {"schema_version": "train-request-v1", "profile_name": "Matte", "genre": "wedding",
            "format_type": "raw", "color_type": "color", "photo_ids": [str(p.id) for p in photos], **overrides}
    return client.post("/v1/jobs/train", json=body)


def _payload(mock_publisher):
    return mock_publisher.enqueue.call_args.args[0].payload


def _ready(store, profile_id):
    profile = store.profiles.get(uuid.UUID(profile_id))
    profile.model_artifact_key = f"models/{profile_id}/model.joblib"
    store.profiles.set_status(profile.id, ProfileStatus.READY)


def test_new_profile_keeps_the_marker_and_lists_it(client, store):
    photos = [_photo(store, "lr-a")]
    resp = _train(client, photos, accepted_marker={"kind": "label", "value": "green"})
    assert resp.status_code == 202
    [listed] = client.get("/v1/profiles").json()
    assert listed["accepted_marker"] == {"kind": "label", "value": "green"}


def test_accepted_photos_reach_the_worker_as_photo_ids(client, store, mock_publisher):
    a, b, c = _photo(store, "lr-a"), _photo(store, "lr-b"), _photo(store, "lr-c")
    _photo(store, "lr-elsewhere")
    resp = _train(client, [a, b, c], accepted_lr_catalog_uuids=["lr-b", "lr-elsewhere", "lr-never-uploaded"])
    assert resp.status_code == 202
    # Only photos of this selection count; unknown catalog uuids are ignored.
    assert _payload(mock_publisher)["accepted"] == [str(b.id)]


def test_a_retrain_keeps_earlier_acceptances_and_updates_the_marker(client, store, mock_publisher):
    a, b = _photo(store, "lr-a"), _photo(store, "lr-b")
    first = _train(client, [a], accepted_lr_catalog_uuids=["lr-a"],
                   accepted_marker={"kind": "rating", "min": 4}).json()
    _ready(store, first["profile_id"])

    resp = _train(client, [b], profile_id=first["profile_id"], accepted_lr_catalog_uuids=["lr-b"],
                  accepted_marker={"kind": "label", "value": "purple"})

    assert resp.status_code == 202
    payload = _payload(mock_publisher)
    assert payload["photo_ids"] == [str(a.id), str(b.id)]
    assert payload["accepted"] == [str(a.id), str(b.id)]
    profile = client.get(f"/v1/profiles/{first['profile_id']}").json()
    assert profile["accepted_marker"] == {"kind": "label", "value": "purple"}


def test_a_retrain_without_marker_keeps_the_profiles(client, store):
    a = _photo(store, "lr-a")
    first = _train(client, [a], accepted_marker={"kind": "rating", "min": 5}).json()
    _ready(store, first["profile_id"])
    _train(client, [a], profile_id=first["profile_id"])
    assert client.get(f"/v1/profiles/{first['profile_id']}").json()["accepted_marker"] == {"kind": "rating", "min": 5}


def test_marker_kind_none_removes_it_on_retrain(client, store):
    a = _photo(store, "lr-a")
    first = _train(client, [a], accepted_marker={"kind": "rating", "min": 5}).json()
    _ready(store, first["profile_id"])
    _train(client, [a], profile_id=first["profile_id"], accepted_marker={"kind": "none"})
    assert client.get(f"/v1/profiles/{first['profile_id']}").json()["accepted_marker"] is None


def test_an_incomplete_or_unknown_marker_is_422(client, store):
    a = _photo(store, "lr-a")
    assert _train(client, [a], accepted_marker={"kind": "label"}).status_code == 422
    assert _train(client, [a], accepted_marker={"kind": "rating", "min": 6}).status_code == 422
    assert _train(client, [a], accepted_marker={"kind": "label", "value": "orange"}).status_code == 422


def test_rename_and_change_the_marker(client, store):
    profile_id = _train(client, [_photo(store, "lr-a")]).json()["profile_id"]
    resp = client.patch(f"/v1/profiles/{profile_id}", json={
        "schema_version": "profile-update-v1", "name": "  Matte 2026 ",
        "accepted_marker": {"kind": "label", "value": "green", "min": 3}})
    assert resp.status_code == 200
    assert (resp.json()["name"], resp.json()["accepted_marker"]) == ("Matte 2026", {"kind": "label", "value": "green"})
    # Only the fields sent change.
    resp = client.patch(f"/v1/profiles/{profile_id}", json={"schema_version": "profile-update-v1", "name": "Matte"})
    assert (resp.json()["name"], resp.json()["accepted_marker"]) == ("Matte", {"kind": "label", "value": "green"})
    resp = client.patch(f"/v1/profiles/{profile_id}", json={"schema_version": "profile-update-v1",
                                                            "accepted_marker": None})
    assert resp.json()["accepted_marker"] is None


def test_rename_refuses_a_blank_name_and_unknown_profiles(client, store):
    profile_id = _train(client, [_photo(store, "lr-a")]).json()["profile_id"]
    body = {"schema_version": "profile-update-v1", "name": "   "}
    assert client.patch(f"/v1/profiles/{profile_id}", json=body).status_code == 422
    assert client.patch(f"/v1/profiles/{uuid.uuid4()}", json={**body, "name": "x"}).status_code == 404
    assert client.patch(f"/v1/profiles/{profile_id}", json={"name": "no schema"}).status_code == 422


def test_a_deleted_profile_is_hidden_everywhere_but_kept(client, store):
    a = _photo(store, "lr-a")
    profile_id = _train(client, [a]).json()["profile_id"]
    _ready(store, profile_id)

    assert client.delete(f"/v1/profiles/{profile_id}").status_code == 204
    assert client.delete(f"/v1/profiles/{profile_id}").status_code == 204  # again: nothing changes

    assert client.get("/v1/profiles").json() == []
    assert client.get(f"/v1/profiles/{profile_id}").status_code == 404
    edit = {"schema_version": "edit-request-v1", "photo_ids": [str(a.id)], "profile_id": profile_id}
    assert client.post("/v1/jobs/edit", json=edit).status_code == 422
    assert _train(client, [a], profile_id=profile_id).status_code == 404
    patch = {"schema_version": "profile-update-v1", "name": "back"}
    assert client.patch(f"/v1/profiles/{profile_id}", json=patch).status_code == 404
    # Soft delete: the record (and with it jobs, results, the model in S3) stays.
    kept = store.profiles.get(uuid.UUID(profile_id))
    assert kept.deleted_at is not None and kept.model_artifact_key == f"models/{profile_id}/model.joblib"


def test_deleting_an_unknown_profile_is_404(client):
    assert client.delete(f"/v1/profiles/{uuid.uuid4()}").status_code == 404
