"""Largest face in a preview (YuNet, MIT): photographers expose for the face, so its
brightness and color are strong features for exposure and white balance."""

from __future__ import annotations

import threading

import numpy as np

from calotype_inference_pipeline.models import model_path

DETECT_EDGE = 640
MIN_SCORE = 0.75

_lock = threading.Lock()
_detector = None


def _get_detector():
    global _detector
    with _lock:
        if _detector is None:
            import cv2

            _detector = cv2.FaceDetectorYN.create(
                str(model_path("yunet")), "", (DETECT_EDGE, DETECT_EDGE), MIN_SCORE, 0.3, 50
            )
        return _detector


def largest_face_box(rgb: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the largest face in preview pixels, or None."""
    import cv2

    h, w = rgb.shape[:2]
    scale = DETECT_EDGE / max(h, w)
    small = cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    detector = _get_detector()
    with _lock:  # the OpenCV detector object is not thread-safe
        detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, found = detector.detect(bgr)
    if found is None or len(found) == 0:
        return None
    best = max(found, key=lambda r: r[2] * r[3])
    x, y, bw, bh = (best[:4] / scale).round().astype(int)
    return int(x), int(y), int(bw), int(bh)
