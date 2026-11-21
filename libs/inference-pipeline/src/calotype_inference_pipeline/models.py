"""Model files: downloaded on first use, verified by SHA-256, never stored in the repo.

Only permissively licensed models (code and weights) are listed here; every entry is also
documented in THIRD_PARTY_MODELS.md. Override the cache folder with CALOTYPE_MODEL_DIR.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelFile:
    name: str
    filename: str
    url: str
    sha256: str
    license: str
    source: str


MODELS: dict[str, ModelFile] = {
    "yunet": ModelFile(
        name="yunet",
        filename="face_detection_yunet_2023mar.onnx",
        url="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        license="MIT",
        source="https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet",
    ),
    "face_landmarker": ModelFile(
        name="face_landmarker",
        filename="face_landmarker.task",
        url="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
        "float16/1/face_landmarker.task",
        sha256="64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        license="Apache-2.0",
        source="https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker",
    ),
    "sface": ModelFile(
        name="sface",
        filename="face_recognition_sface_2021dec.onnx",
        url="https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        license="Apache-2.0",
        source="https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface",
    ),
}


def model_dir() -> Path:
    for var in ("CALOTYPE_MODEL_DIR", "TARSIER_MODEL_DIR", "LRFF_MODEL_DIR"):
        if env := os.environ.get(var):
            return Path(env)
    base = Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache"))
    new = base / "Calotype" / "models"
    for name in ("Tarsier", "LRFrameFlow"):   # cache from before the rename (ADR 006): move it
        old = base / name / "models"
        if not new.exists() and old.is_dir():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
                old.parent.rmdir()          # the old app folder, if nothing else is in it
            except OSError:
                if not new.exists():
                    return old
    return new


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_path(name: str, *, download: bool = True) -> Path:
    """Local path of a verified model file, downloading it if needed."""
    spec = MODELS[name]
    path = model_dir() / spec.filename
    if path.exists() and _sha256(path) == spec.sha256:
        return path
    if not download:
        raise FileNotFoundError(f"model {name} not found at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".download")
    urllib.request.urlretrieve(spec.url, tmp)  # noqa: S310 — fixed https URLs above
    digest = _sha256(tmp)
    if digest != spec.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"model {name}: checksum mismatch ({digest}), refusing to use it")
    tmp.replace(path)
    return path
