"""Learned culling scorer: weights from the photographer's own decisions (ADR 005).

Same features as the baseline, but how much each one counts is learned from labels
(e.g. 5 stars / picked = keep). Logistic regression keeps it explainable: every decision
can be broken down into "this pushed it up, that pushed it down".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from tarsier_culling.analyze import PhotoFeatures
from tarsier_culling.scoring import group_series

# One feature per idea: two near-identical features (e.g. sharpness and its rank in the shoot)
# get opposite weights that cancel out, and the explanations then contradict each other.
FEATURES = [
    "subject_sharpness", "sharpness_rank_in_series", "best_in_series",
    "series_size_log", "face_count", "largest_face", "eyes_closed", "looking_down", "smile",
    "mouth_open",
    "laughing_closed_eyes", "no_face", "face_clipped", "clipped_highlights", "mean_luma",
    "crushed_shadows",
    # Compared with the rest of its series: of near-identical shots the photographer keeps the
    # one with the best expression, not only the sharpest (ROC-AUC 0.628 → 0.658 against a
    # photographer's exports on five kindergarten groups, each held out as a whole).
    "smile_rank_in_series", "eyes_open_rank_in_series", "face_size_rank_in_series",
    "mouth_open_rank_in_series",
]

# Readable name for a high / low value of each feature: explanations describe the photo
# ("eyes open", "small series"), not the feature ("eyes closed" with a minus sign).
LABELS = {
    "subject_sharpness": ("sharp subject", "soft subject"),
    "sharpness_rank_in_series": ("sharper than its series", "softer than its series"),
    "best_in_series": ("best of its series", "not the best of its series"),
    "series_size_log": ("one of many similar shots", "few similar shots"),
    "face_count": ("several faces", "few faces"),
    "largest_face": ("large face", "small or no face"),
    "eyes_closed": ("eyes closed", "eyes open"),
    "looking_down": ("looking down", "looking up or ahead"),
    "smile": ("smiling", "no smile"),
    "mouth_open": ("mouth open", "mouth closed"),
    "laughing_closed_eyes": ("laughing with closed eyes", "no laughing with closed eyes"),
    "no_face": ("no face", "a face"),
    "face_clipped": ("blown-out face", "face not blown out"),
    "clipped_highlights": ("blown highlights", "highlights intact"),
    "mean_luma": ("bright", "dark"),
    "crushed_shadows": ("crushed shadows", "open shadows"),
    "smile_rank_in_series": ("best smile of its series", "weaker smile than its series"),
    "eyes_open_rank_in_series": ("eyes more open than its series", "eyes less open than its series"),
    "face_size_rank_in_series": ("closer than its series", "farther than its series"),
    "mouth_open_rank_in_series": ("mouth more open than its series", "mouth more closed than its series"),
}


def _rank(values: np.ndarray) -> np.ndarray:
    n = len(values)
    if n < 2:
        return np.full(n, 0.5)
    below = (values[:, None] > values[None, :]).sum(axis=1)
    equal = (values[:, None] == values[None, :]).sum(axis=1) - 1
    return (below + 0.5 * equal) / (n - 1)


def feature_matrix(photos: list[PhotoFeatures]) -> np.ndarray:
    """One row per photo, in FEATURES order. Ranks are within the given shoot."""
    series = np.array(group_series(photos))
    sharp = np.array([p.subject_sharpness for p in photos], dtype=float)
    cues = np.array([
        [p.smile or 0.0, 1.0 - (p.eyes_closed or 0.0),
         max((f.rel_size for f in p.relevant_faces), default=0.0),
         max((f.mouth_open or 0.0 for f in p.relevant_faces), default=0.0)]
        for p in photos
    ], dtype=float).reshape(len(photos), 4)
    series_rank = np.full(len(photos), 0.5)
    cue_rank = np.full((len(photos), 4), 0.5)
    best = np.zeros(len(photos))
    sizes = np.zeros(len(photos))
    for s in set(series.tolist()):
        idx = np.where(series == s)[0]
        sizes[idx] = len(idx)
        if len(idx) > 1:
            series_rank[idx] = _rank(sharp[idx])
            best[idx[np.argmax(sharp[idx])]] = 1.0
            for j in range(4):
                cue_rank[idx, j] = _rank(cues[idx, j])
        else:
            best[idx] = 1.0
    rows = []
    for i, p in enumerate(photos):
        faces = p.relevant_faces
        rows.append([
            p.subject_sharpness, series_rank[i], best[i], np.log(sizes[i]),
            len(p.faces), max((f.rel_size for f in faces), default=0.0) ** 0.5,
            p.eyes_closed or 0.0,
            max((f.looking_down or 0.0 for f in faces), default=0.0),
            p.smile or 0.0, max((f.mouth_open or 0.0 for f in faces), default=0.0),
            float(p.laughing_closed_eyes), float(not p.faces), p.face_clipped, p.clipped_highlights,
            p.mean_luma, p.crushed_shadows, *cue_rank[i],
        ])
    return np.array(rows, dtype=float)


@dataclass
class LearnedScorer:
    scaler: StandardScaler
    model: LogisticRegression

    @classmethod
    def fit(cls, photos: list[PhotoFeatures], keep: list[bool]) -> LearnedScorer:
        X = feature_matrix(photos)
        scaler = StandardScaler().fit(X)
        model = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
        model.fit(scaler.transform(X), np.asarray(keep, dtype=int))
        return cls(scaler, model)

    @classmethod
    def fit_subset(cls, photos: list[PhotoFeatures], rows: list[int], keep: list[bool]) -> LearnedScorer:
        """Fit on some photos of a shoot; series and ranks still come from the whole shoot."""
        X = feature_matrix(photos)[rows]
        scaler = StandardScaler().fit(X)
        model = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
        model.fit(scaler.transform(X), np.asarray(keep, dtype=int))
        return cls(scaler, model)

    def keep_probability(self, photos: list[PhotoFeatures]) -> np.ndarray:
        return self.model.predict_proba(self.scaler.transform(feature_matrix(photos)))[:, 1]

    def weights(self) -> list[tuple[str, float]]:
        """Learned weight per feature (on standardized features), strongest first."""
        pairs = zip(FEATURES, self.model.coef_[0])
        return sorted(((LABELS[f][0], float(w)) for f, w in pairs), key=lambda x: -abs(x[1]))

    def explain(self, photos: list[PhotoFeatures], top: int = 3) -> list[str]:
        """Per photo: the features that moved the decision most, as readable text."""
        Z = self.scaler.transform(feature_matrix(photos))
        contrib = Z * self.model.coef_[0]
        out = []
        for z, row in zip(Z, contrib):
            idx = np.argsort(-np.abs(row))[:top]
            parts = []
            for j in idx:
                high, low = LABELS[FEATURES[j]]
                parts.append(f"{'+' if row[j] > 0 else '−'} {high if z[j] > 0 else low}")
            out.append("; ".join(parts))
        return out
