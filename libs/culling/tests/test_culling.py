"""Culling features and baseline rules — no face images needed."""

from __future__ import annotations

import cv2
import numpy as np

from tarsier_culling.analyze import PhotoFeatures
from tarsier_culling.faces import Face
from tarsier_culling.scoring import SERIES_MAX_DISTANCE, group_series, score
from tarsier_culling.technical import dhash, exposure, hamming, region_sharpness, sharpness


def _texture(seed: int = 0, size: int = 800) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 256, (size // 8, size // 8), dtype=np.uint8)
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_NEAREST)


def test_blur_lowers_sharpness():
    crisp = _texture()
    soft = cv2.GaussianBlur(crisp, (0, 0), 3)
    assert sharpness(crisp) > sharpness(soft) + 0.5


def test_small_regions_are_not_upscaled():
    crisp = _texture(size=800)
    # the same crisp content as a small "distant face" must not look blurrier than a big one
    small = cv2.resize(crisp, (80, 80), interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((800, 800), np.uint8)
    canvas[0:80, 0:80] = small
    assert region_sharpness(canvas, (0, 0, 80, 80)) > 1.5


def test_exposure_measures_clipping():
    img = np.full((100, 100), 128, np.uint8)
    img[:10] = 255
    e = exposure(img)
    assert abs(e["clipped_highlights"] - 0.10) < 1e-6
    assert e["crushed_shadows"] == 0.0


def test_dhash_groups_near_duplicates_only():
    a = _texture(1)
    b = cv2.GaussianBlur(a, (0, 0), 1.2)       # same scene, slightly different
    c = _texture(2)                            # different scene
    assert hamming(dhash(a), dhash(b)) <= SERIES_MAX_DISTANCE
    assert hamming(dhash(a), dhash(c)) > SERIES_MAX_DISTANCE


def _photo(name, sharp, *, eyes=0.05, smile=0.0, h=0, faces=True) -> PhotoFeatures:
    face = Face(box=(100, 100, 120, 150), score=0.9, rel_size=0.02, sharpness=sharp,
                eyes_closed=eyes, smile=smile, mouth_open=0.1)
    return PhotoFeatures(name=name, width=1200, height=800, sharpness=sharp, center_sharpness=sharp,
                         mean_luma=0.45, clipped_highlights=0.0, crushed_shadows=0.0,
                         dhash=h, faces=[face] if faces else [])


def _spread(n=8):
    """Distinct scenes so photos do not form one series."""
    return [(1 << (8 * i)) - 1 for i in range(n)]


def test_series_are_consecutive_lookalikes():
    hashes = [0, 1, 3, (1 << 40) - 1, (1 << 40) - 1]
    photos = [_photo(str(i), 2.0, h=x) for i, x in enumerate(hashes)]
    assert group_series(photos) == [0, 0, 0, 1, 1]


def test_laughing_with_closed_eyes_is_not_punished():
    hs = _spread()
    photos = [_photo(f"p{i}", 2.0 + 0.05 * i, h=hs[i]) for i in range(6)]
    photos.append(_photo("laugh", 2.2, eyes=0.9, smile=0.9, h=hs[6]))
    photos.append(_photo("blink", 2.2, eyes=0.9, smile=0.0, h=hs[7]))
    d = {x.name: x for x in score(photos)}
    assert d["laugh"].bucket == "keep"
    assert "a moment" in d["laugh"].explanation
    assert d["blink"].bucket == "reject"
    assert "eyes closed" in d["blink"].explanation


def test_strong_expression_softens_blur_penalty():
    hs = _spread()
    photos = [_photo(f"p{i}", 2.5 + 0.05 * i, h=hs[i]) for i in range(6)]
    photos.append(_photo("blurry_flat", 1.0, h=hs[6]))
    photos.append(_photo("blurry_joyful", 1.0, smile=0.9, h=hs[7]))
    d = {x.name: x for x in score(photos)}
    assert d["blurry_joyful"].score > d["blurry_flat"].score + 0.4
    assert d["blurry_joyful"].bucket != "reject"
    assert d["blurry_flat"].bucket == "reject"


def test_best_of_series_is_preferred_and_rest_goes_to_review():
    photos = [_photo("a", 2.0, h=0), _photo("b", 2.6, h=1), _photo("c", 2.1, h=3)]
    d = {x.name: x for x in score(photos)}
    assert "best of a series of 3" in d["b"].explanation
    assert d["b"].score > d["a"].score and d["b"].score > d["c"].score
    assert all("better shot" in d[n].explanation for n in "ac")


def test_near_duplicate_alone_goes_to_review_not_reject():
    photos = [_photo("a", 2.5, h=0), _photo("b", 2.5, h=1)]
    d = {x.name: x for x in score(photos)}
    assert {d["a"].bucket, d["b"].bucket} <= {"keep", "uncertain"}


def test_bright_background_is_fine_but_blown_face_is_not():
    hs = _spread(4)
    photos = [_photo(f"p{i}", 2.5, h=hs[i]) for i in range(4)]
    photos[1].clipped_highlights = 0.18          # bright window behind the person
    photos[2].face_clipped = 0.4                 # the face itself is blown out
    d = {x.name: x for x in score(photos)}
    assert "blown" not in d["p1"].explanation
    assert "face overexposed" in d["p2"].explanation


def test_photos_without_faces_still_get_a_decision():
    hs = _spread(3)
    photos = [_photo(f"p{i}", 2.0 + i, h=hs[i], faces=False) for i in range(3)]
    assert all(x.bucket in {"keep", "uncertain", "reject"} for x in score(photos))


def test_learned_scorer_picks_up_the_photographers_taste():
    """Labels say: smiles are kept, closed eyes are not. The weights must follow."""
    from tarsier_culling.learned import LearnedScorer

    rng = np.random.default_rng(0)
    photos, keep = [], []
    for i in range(200):
        smile, eyes = float(rng.random()), float(rng.random())
        photos.append(_photo(f"p{i}", 2.0 + 0.3 * rng.random(), eyes=eyes, smile=smile,
                             h=int(rng.integers(0, 1 << 62))))
        keep.append(smile > 0.5 and eyes < 0.6)
    scorer = LearnedScorer.fit(photos, keep)
    weights = dict(scorer.weights())
    assert weights["smiling"] > 0.5
    assert weights["eyes closed"] < -0.5
    p = scorer.keep_probability(photos)
    assert p[np.array(keep)].mean() > p[~np.array(keep)].mean() + 0.3
    text = scorer.explain([_photo("x", 2.1, eyes=0.9, smile=0.0, h=1)])[0]
    assert "eyes closed" in text or "no smile" in text
