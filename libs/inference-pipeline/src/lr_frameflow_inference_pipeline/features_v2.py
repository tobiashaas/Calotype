"""Feature version 2: histogram + tone/color statistics + face brightness/color.

Measured on 1,837 edited photos (367 held out, gradient boosting): exposure within
±0.15 EV for 56 % of photos instead of 31 % with the v1 histogram + Ridge, all of
exposure/temperature/tint right for 34 % instead of 14 % (tools/lrff_eval/model_lab.py).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, UnidentifiedImageError

from lr_frameflow_inference_pipeline.faces import largest_face_box
from lr_frameflow_inference_pipeline.features import FEATURE_DIM as HIST_DIM
from lr_frameflow_inference_pipeline.features import extract_features as histogram_features

FEATURE_VERSION_V2 = "histstats-face-v2"
STATS_EDGE = 400          # statistics barely change below full size, ~10x faster
STATS_DIM = 20
FACE_DIM = 5
FEATURE_DIM_V2 = HIST_DIM + STATS_DIM + FACE_DIM


def _luma(f: np.ndarray) -> np.ndarray:
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


def tone_color_stats(rgb: np.ndarray) -> list[float]:
    f = rgb.astype(np.float32) / 255.0
    luma = _luma(f)
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    pct = np.percentile(luma, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    mean_rgb = f.reshape(-1, 3).mean(axis=0)
    return [
        *pct, float(luma.mean()), float(luma.std()), *mean_rgb,
        float(mean_rgb[2] - mean_rgb[0]),                       # blue vs. red
        float(mean_rgb[1] - (mean_rgb[0] + mean_rgb[2]) / 2),   # green vs. magenta
        float(sat.mean()), float(np.percentile(sat, 90)),
        float((luma > 0.98).mean()), float((luma < 0.02).mean()),
    ]


def face_stats(rgb: np.ndarray, box: tuple[int, int, int, int] | None) -> list[float]:
    """[has_face, median luma, mean luma, blue−red, green−magenta] of the face; the whole
    image stands in when there is no face (flag 0), so the vector never has gaps."""
    f = rgb.astype(np.float32) / 255.0
    if box is not None:
        x, y, w, h = box
        crop = f[max(0, y): y + h, max(0, x): x + w]
        if crop.size:
            luma = _luma(crop)
            m = crop.reshape(-1, 3).mean(axis=0)
            return [1.0, float(np.median(luma)), float(luma.mean()),
                    float(m[2] - m[0]), float(m[1] - (m[0] + m[2]) / 2)]
    luma = _luma(f)
    return [0.0, float(np.median(luma)), float(luma.mean()), 0.0, 0.0]


def extract_features_v2(image_bytes: bytes) -> list[float]:
    """153 floats. Raises ValueError for undecodable images (never a silent zero vector)."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("preview cannot be decoded") from exc
    rgb = np.asarray(img)
    box = largest_face_box(rgb)
    scale = min(1.0, STATS_EDGE / max(rgb.shape[:2]))
    if scale < 1.0:
        small = np.asarray(img.resize((round(img.width * scale), round(img.height * scale)),
                                      Image.BILINEAR))
        box = tuple(round(v * scale) for v in box) if box else None
    else:
        small = rgb
    return histogram_features(image_bytes) + tone_color_stats(small) + face_stats(small, box)
