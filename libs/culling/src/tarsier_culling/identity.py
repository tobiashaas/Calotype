"""Who is in the photo: a face embedding per photo and groups of photos showing the same person.

Culling often means "the best few photos of each person" (a kindergarten shoot, a team, guests).
The main face (largest YuNet detection) is aligned on its five landmarks and turned into a
128-dim SFace embedding; photos are grouped by cosine similarity. Embeddings never leave the
machine and are not stored with the photos' metadata.
"""

from __future__ import annotations

import cv2
import numpy as np
from sklearn.cluster import AgglomerativeClustering

from tarsier_culling.models import model_path

DETECT_EDGE = 960
MIN_SCORE = 0.75
# Average-linkage merge level (cosine similarity). SFace's pairwise "same person" threshold is
# 0.363, but over a whole shoot that merges siblings and similar children: on kindergarten
# groups 0.4 merged several children into one, 0.6 gives one group of 45–80 portraits per child.
SAME_PERSON = 0.60


class IdentityEmbedder:
    def __init__(self) -> None:
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path("yunet")), "", (DETECT_EDGE, DETECT_EDGE), MIN_SCORE, 0.3, 50
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(model_path("sface")), "")

    def embed(self, rgb: np.ndarray) -> np.ndarray | None:
        """Unit-length embedding of the largest face, or None without a face."""
        h, w = rgb.shape[:2]
        scale = min(1.0, DETECT_EDGE / max(h, w))
        small = cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
        self._detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, found = self._detector.detect(bgr)
        if found is None or len(found) == 0:
            return None
        main = max(found, key=lambda r: r[2] * r[3])
        aligned = self._recognizer.alignCrop(bgr, main)
        vec = self._recognizer.feature(aligned).astype(np.float32).ravel()
        n = float(np.linalg.norm(vec))
        return vec / n if n else None


def group_people(embeddings: list[np.ndarray | None], same_person: float = SAME_PERSON) -> list[int]:
    """Person id per photo (-1 = no face). Ids are dense, in order of first appearance."""
    idx = [i for i, e in enumerate(embeddings) if e is not None]
    out = [-1] * len(embeddings)
    if not idx:
        return out
    if len(idx) == 1:
        out[idx[0]] = 0
        return out
    X = np.stack([embeddings[i] for i in idx])
    labels = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=1.0 - same_person
    ).fit_predict(X)
    order: dict[int, int] = {}
    for i, lab in zip(idx, labels):
        out[i] = order.setdefault(int(lab), len(order))
    return out
