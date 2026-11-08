"""Per-photo culling features from a Bridge preview (≤ 1200 px, upright, unedited)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from calotype_culling.faces import Face, FaceAnalyzer
from calotype_culling.technical import center_sharpness, dhash, exposure, sharpness

# Faces much smaller than the largest one are background people; they do not decide.
RELEVANT_FACE_FRACTION = 0.25


@dataclass
class PhotoFeatures:
    name: str
    width: int
    height: int
    sharpness: float
    center_sharpness: float
    mean_luma: float
    clipped_highlights: float
    crushed_shadows: float
    dhash: int
    faces: list[Face] = field(default_factory=list)
    face_clipped: float = 0.0          # share of blown-out pixels on the relevant faces

    # --- aggregates over the relevant faces -------------------------------------------

    @property
    def relevant_faces(self) -> list[Face]:
        if not self.faces:
            return []
        largest = max(f.rel_size for f in self.faces)
        return [f for f in self.faces if f.rel_size >= RELEVANT_FACE_FRACTION * largest]

    @property
    def subject_sharpness(self) -> float:
        """Sharpness where it matters: the sharpest relevant face, else the image center."""
        faces = self.relevant_faces
        return max(f.sharpness for f in faces) if faces else self.center_sharpness

    def _max(self, attr: str) -> float | None:
        values = [getattr(f, attr) for f in self.relevant_faces if getattr(f, attr) is not None]
        return max(values) if values else None

    @property
    def eyes_closed(self) -> float | None:
        return self._max("eyes_closed")

    @property
    def smile(self) -> float | None:
        return self._max("smile")

    @property
    def laughing_closed_eyes(self) -> bool:
        return any(f.laughing_closed_eyes for f in self.relevant_faces)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dhash"] = f"{self.dhash:016x}"
        for f, raw in zip(self.faces, d["faces"]):
            raw.pop("blendshapes")
            raw["laughing_closed_eyes"] = f.laughing_closed_eyes
        d.update(
            subject_sharpness=self.subject_sharpness,
            eyes_closed=self.eyes_closed,
            smile=self.smile,
            laughing_closed_eyes=self.laughing_closed_eyes,
            face_count=len(self.faces),
        )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PhotoFeatures:
        """Inverse of to_dict (blendshapes are not kept)."""
        faces = [Face(box=tuple(f["box"]), score=f["score"], rel_size=f["rel_size"],
                      sharpness=f["sharpness"], eyes_closed=f.get("eyes_closed"), smile=f.get("smile"),
                      mouth_open=f.get("mouth_open"), looking_down=f.get("looking_down"),
                      head_pitch=f.get("head_pitch")) for f in d.get("faces", [])]
        return cls(name=d["name"], width=d["width"], height=d["height"], sharpness=d["sharpness"],
                   center_sharpness=d["center_sharpness"], mean_luma=d["mean_luma"],
                   clipped_highlights=d["clipped_highlights"], crushed_shadows=d["crushed_shadows"],
                   dhash=int(d["dhash"], 16), faces=faces, face_clipped=d.get("face_clipped", 0.0))


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def analyze(path: Path, faces: FaceAnalyzer | None) -> PhotoFeatures:
    return analyze_rgb(load_rgb(path), path.name, faces)


def analyze_rgb(rgb: np.ndarray, name: str, faces: FaceAnalyzer | None) -> PhotoFeatures:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    exp = exposure(gray)
    found = faces.analyze(rgb, gray) if faces else []
    photo = PhotoFeatures(
        name=name,
        width=rgb.shape[1],
        height=rgb.shape[0],
        sharpness=sharpness(gray),
        center_sharpness=center_sharpness(gray),
        mean_luma=exp["mean_luma"],
        clipped_highlights=exp["clipped_highlights"],
        crushed_shadows=exp["crushed_shadows"],
        dhash=dhash(gray),
        faces=found,
    )
    # A bright window behind someone is fine; a blown-out face is not.
    boxes = [f.box for f in photo.relevant_faces]
    if boxes:
        clipped = [
            float((gray[max(0, y): y + h, max(0, x): x + w] >= 250).mean())
            for x, y, w, h in boxes
            if w > 0 and h > 0
        ]
        photo.face_clipped = max(clipped, default=0.0)
    return photo
