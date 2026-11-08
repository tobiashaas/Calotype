"""Grouping photos by person (embeddings are synthetic here; the model is not needed)."""

from __future__ import annotations

import numpy as np

from calotype_culling.identity import group_people


def _person(rng: np.random.Generator, center: np.ndarray, n: int) -> list[np.ndarray]:
    out = []
    for _ in range(n):
        v = center + rng.normal(0, 0.03, center.shape)
        out.append(v / np.linalg.norm(v))
    return out


def test_photos_of_the_same_person_end_up_together():
    rng = np.random.default_rng(3)
    a, b = rng.normal(size=128), rng.normal(size=128)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    emb = _person(rng, a, 4) + [None] + _person(rng, b, 3)
    ids = group_people(emb)
    assert ids[4] == -1                      # no face
    assert len(set(ids[:4])) == 1 and len(set(ids[5:])) == 1
    assert ids[0] != ids[5]
    assert ids[0] == 0                       # dense ids in order of appearance


def test_no_faces_and_single_face():
    assert group_people([None, None]) == [-1, -1]
    v = np.ones(128) / np.sqrt(128)
    assert group_people([None, v]) == [-1, 0]
