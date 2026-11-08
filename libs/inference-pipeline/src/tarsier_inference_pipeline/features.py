"""Real feature extraction from JPEG previews (Pillow-based, no GPU)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, UnidentifiedImageError

FEATURE_DIM = 128  # 4 channels × 32 histogram bins
FEATURE_MODEL_VERSION = "histogram-v1"  # stored with every FeatureVector; bump on layout change
_BINS = 32
_TARGET_SIZE = (256, 256)

LR_PARAMS = [
    "exposure", "temp", "tint", "contrast",
    "highlights", "shadows", "whites", "blacks",
    "vibrance", "saturation",
]


def extract_features(image_bytes: bytes) -> list[float]:
    """Extract 128-dim feature vector from JPEG bytes.

    Returns a zero-vector if the image cannot be decoded (graceful fallback).

    Vector layout:
      [0:32]   R-channel histogram (32 bins, normalized)
      [32:64]  G-channel histogram
      [64:96]  B-channel histogram
      [96:128] Brightness histogram  max(R, G, B) per pixel
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = img.resize(_TARGET_SIZE, Image.LANCZOS)
    except (UnidentifiedImageError, Exception):
        return [0.0] * FEATURE_DIM

    arr = np.asarray(img, dtype=np.float32) / 255.0  # (H, W, 3), range [0, 1]

    features: list[float] = []

    # R, G, B histograms
    for ch in range(3):
        hist, _ = np.histogram(arr[:, :, ch], bins=_BINS, range=(0.0, 1.0))
        total = hist.sum() or 1
        features.extend((hist / total).tolist())

    # Brightness channel = max(R, G, B)
    brightness = arr.max(axis=2)
    hist_v, _ = np.histogram(brightness, bins=_BINS, range=(0.0, 1.0))
    total = hist_v.sum() or 1
    features.extend((hist_v / total).tolist())

    return features  # 128 floats
