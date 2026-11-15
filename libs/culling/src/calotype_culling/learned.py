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

from calotype_culling.analyze import PhotoFeatures
from calotype_culling.scoring import group_series

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


# Lightroom's assisted culling (Lightroom Classic 15+), read from the catalog by the Bridge
# (`lr_metadata.lr_culling`). Used as extra features when nearly every photo of the job has
# them: the weights come from the photographer's decisions like for our own features.
LIGHTROOM_FEATURES = [
    "subject_sharpness", "eye_sharpness", "eyes_open_state", "bad_exposure", "misfire",
    "aesthetic", "combined", "face", "frame", "severe_blur", "over_exposure", "under_exposure",
    "ground_shot",
]
LIGHTROOM_LABELS = {
    "subject_sharpness": ("Lightroom: sharp subject", "Lightroom: soft subject"),
    "eye_sharpness": ("Lightroom: sharp eyes", "Lightroom: soft eyes"),
    "eyes_open_state": ("Lightroom: eyes open", "Lightroom: eyes not open"),
    "bad_exposure": ("Lightroom: exposure problem", "Lightroom: exposure fine"),
    "misfire": ("Lightroom: accidental shot", "Lightroom: intended shot"),
    "aesthetic": ("Lightroom: appealing", "Lightroom: less appealing"),
    "combined": ("Lightroom: good frame overall", "Lightroom: weaker frame overall"),
    "face": ("Lightroom: good faces", "Lightroom: weaker faces"),
    "frame": ("Lightroom: good frame", "Lightroom: weaker frame"),
    "severe_blur": ("Lightroom: badly blurred", "Lightroom: not blurred"),
    "over_exposure": ("Lightroom: overexposed", "Lightroom: not overexposed"),
    "under_exposure": ("Lightroom: underexposed", "Lightroom: not underexposed"),
    "ground_shot": ("Lightroom: shot of the ground", "Lightroom: not a shot of the ground"),
}
# Share of the job's photos that must carry a score before it is used (the rest get the median).
LIGHTROOM_MIN_SHARE = 0.9


def lightroom_matrix(scores: list[dict | None] | None) -> tuple[list[str], np.ndarray | None]:
    """Lightroom's scores as extra feature columns: (names, one row per photo) or ([], None).

    A score counts when at least LIGHTROOM_MIN_SHARE of the photos have it and it varies;
    photos without it get the median of the others.
    """
    if not scores:
        return [], None
    n = len(scores)
    names, cols = [], []
    for name in LIGHTROOM_FEATURES:
        values = [s.get(name) if isinstance(s, dict) else None for s in scores]
        known = [float(v) for v in values if isinstance(v, (int, float)) and np.isfinite(v)]
        if len(known) < LIGHTROOM_MIN_SHARE * n or len(set(known)) < 2:
            continue
        median = float(np.median(known))
        names.append(name)
        cols.append([float(v) if isinstance(v, (int, float)) and np.isfinite(v) else median for v in values])
    if not names:
        return [], None
    return names, np.array(cols, dtype=float).T


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
    # Lightroom score columns appended after FEATURES (see lightroom_matrix), in this order.
    lightroom: tuple[str, ...] = ()

    @staticmethod
    def _matrix(photos: list[PhotoFeatures], extra: np.ndarray | None) -> np.ndarray:
        X = feature_matrix(photos)
        return X if extra is None else np.hstack([X, extra])

    @classmethod
    def fit(cls, photos: list[PhotoFeatures], keep: list[bool]) -> LearnedScorer:
        return cls.fit_subset(photos, list(range(len(photos))), keep)

    @classmethod
    def fit_subset(cls, photos: list[PhotoFeatures], rows: list[int], keep: list[bool],
                   lightroom: list[dict | None] | None = None) -> LearnedScorer:
        """Fit on some photos of a shoot; series and ranks still come from the whole shoot.

        lightroom: per photo Lightroom's assisted-culling scores (or None) — extra features.
        """
        names, extra = lightroom_matrix(lightroom)
        X = cls._matrix(photos, extra)[rows]
        scaler = StandardScaler().fit(X)
        model = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
        model.fit(scaler.transform(X), np.asarray(keep, dtype=int))
        return cls(scaler, model, tuple(names))

    def _features(self, photos: list[PhotoFeatures], lightroom: list[dict | None] | None) -> np.ndarray:
        if not self.lightroom:
            return feature_matrix(photos)
        names, extra = lightroom_matrix(lightroom)
        # Same columns as when fitted; a score now missing for too many photos counts as its median.
        cols = []
        for name in self.lightroom:
            if extra is not None and name in names:
                cols.append(extra[:, names.index(name)])
            else:
                cols.append(np.full(len(photos), self.scaler.mean_[len(FEATURES) + self.lightroom.index(name)]))
        return np.hstack([feature_matrix(photos), np.array(cols).T])

    def keep_probability(self, photos: list[PhotoFeatures],
                         lightroom: list[dict | None] | None = None) -> np.ndarray:
        return self.model.predict_proba(self.scaler.transform(self._features(photos, lightroom)))[:, 1]

    @property
    def _names(self) -> list[str]:
        return FEATURES + [f"lr_{n}" for n in self.lightroom]

    def _label(self, name: str) -> tuple[str, str]:
        return LIGHTROOM_LABELS[name[3:]] if name.startswith("lr_") else LABELS[name]

    def weights(self) -> list[tuple[str, float]]:
        """Learned weight per feature (on standardized features), strongest first."""
        pairs = zip(self._names, self.model.coef_[0])
        return sorted(((self._label(f)[0], float(w)) for f, w in pairs), key=lambda x: -abs(x[1]))

    def explain(self, photos: list[PhotoFeatures], top: int = 3,
                lightroom: list[dict | None] | None = None) -> list[str]:
        """Per photo: the features that moved the decision most, as readable text."""
        Z = self.scaler.transform(self._features(photos, lightroom))
        contrib = Z * self.model.coef_[0]
        names = self._names
        out = []
        for z, row in zip(Z, contrib):
            idx = np.argsort(-np.abs(row))[:top]
            parts = []
            for j in idx:
                high, low = self._label(names[j])
                parts.append(f"{'+' if row[j] > 0 else '−'} {high if z[j] > 0 else low}")
            out.append("; ".join(parts))
        return out
