"""cull(): learn from decided photos when there are enough, else the starter rules."""

from __future__ import annotations

import json

from tarsier_culling.analyze import PhotoFeatures
from tarsier_culling.cull import cull, decision_from_metadata
from tarsier_culling.faces import Face


def _photo(i: int, sharp: float, eyes_closed: float) -> PhotoFeatures:
    face = Face(box=(100, 100, 200, 200), score=0.9, rel_size=0.08, sharpness=sharp,
                eyes_closed=eyes_closed, smile=0.3, mouth_open=0.1, looking_down=0.1)
    return PhotoFeatures(name=f"p{i}.jpg", width=1200, height=800, sharpness=sharp, center_sharpness=sharp,
                         mean_luma=0.45, clipped_highlights=0.0, crushed_shadows=0.0,
                         dhash=(i * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF, faces=[face])


def test_decisions_from_metadata():
    assert decision_from_metadata({"pick_status": 1, "rating": 1}) is True
    assert decision_from_metadata({"pick_status": -1, "rating": 5}) is False
    assert decision_from_metadata({"rating": 4}) is True
    assert decision_from_metadata({"rating": 2}) is False
    assert decision_from_metadata({"rating": 0, "pick_status": 0}) is None
    assert decision_from_metadata(None) is None


def test_learns_from_enough_decisions_and_explains():
    # The photographer keeps open eyes, rejects closed eyes — sharpness does not matter here.
    photos, decisions = [], []
    for i in range(40):
        closed = 0.9 if i % 2 else 0.05
        photos.append(_photo(i, sharp=100 + (i * 37) % 50, eyes_closed=closed))
        decisions.append(None if i >= 30 else closed < 0.5)
    res = cull(photos, decisions)
    assert {r.method for r in res} == {"learned"}
    new = res[30:]
    assert all(r.bucket == "keep" for r, p in zip(new, photos[30:]) if p.eyes_closed < 0.5)
    assert all(r.bucket == "reject" for r, p in zip(new, photos[30:]) if p.eyes_closed > 0.5)
    assert "eyes" in new[0].reason


def test_falls_back_to_rules_without_decisions():
    photos = [_photo(i, sharp=100 + i, eyes_closed=0.05) for i in range(6)]
    res = cull(photos, [None] * 6)
    assert {r.method for r in res} == {"rules"} and len(res) == 6
    assert all(r.bucket in {"keep", "uncertain", "reject"} and r.reason for r in res)


def test_features_survive_a_round_trip():
    p = _photo(3, 120.0, 0.2)
    q = PhotoFeatures.from_dict(json.loads(json.dumps(p.to_dict())))
    assert (q.name, q.dhash, q.faces[0].eyes_closed, q.subject_sharpness) == (p.name, p.dhash, 0.2, p.subject_sharpness)
