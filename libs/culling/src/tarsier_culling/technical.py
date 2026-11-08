"""Technical image measures: sharpness, exposure, a perceptual hash for series."""

from __future__ import annotations

import cv2
import numpy as np

# Sharpness is measured at a fixed size so values are comparable across previews.
_SHARP_EDGE = 1024
_FACE_EDGE = 256


def _resize_long_edge(gray: np.ndarray, edge: int) -> np.ndarray:
    h, w = gray.shape[:2]
    scale = edge / max(h, w)
    if abs(scale - 1.0) < 1e-3:
        return gray
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(gray, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=interp)


def sharpness(gray: np.ndarray, edge: int = _SHARP_EDGE) -> float:
    """Variance of the Laplacian at a fixed size, as log10 (≈ 1 blurry … 3+ crisp)."""
    if gray.size == 0:
        return 0.0
    small = _resize_long_edge(gray, edge)
    var = float(cv2.Laplacian(small, cv2.CV_64F).var())
    return float(np.log10(var + 1.0))


def region_sharpness(gray: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """Sharpness of a region (e.g. a face). Large regions are reduced to a fixed size;
    small ones are measured as they are — upscaling would blur them and make every
    distant face look unsharp."""
    x, y, w, h = box
    crop = gray[max(0, y): y + h, max(0, x): x + w]
    if not crop.size:
        return 0.0
    return sharpness(crop, min(_FACE_EDGE, max(crop.shape[:2])))


def center_sharpness(gray: np.ndarray) -> float:
    """Sharpness of the central third — a stand-in for the subject when no face is found."""
    h, w = gray.shape[:2]
    return region_sharpness(gray, (w // 3, h // 3, w // 3, h // 3))


def exposure(gray: np.ndarray) -> dict[str, float]:
    g = gray.astype(np.float32) / 255.0
    return {
        "mean_luma": float(g.mean()),
        "clipped_highlights": float((g >= 0.98).mean()),
        "crushed_shadows": float((g <= 0.02).mean()),
    }


def dhash(gray: np.ndarray, size: int = 8) -> int:
    """Difference hash: 64 bits, robust to small shifts and exposure changes."""
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
