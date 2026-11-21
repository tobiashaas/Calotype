"""Faces: YuNet finds them (also small/distant ones), MediaPipe reads each face crop.

MediaPipe's face landmarker is tuned for close faces, so it runs on a crop around every
YuNet detection. Its blendshapes give the expression directly:
eyeBlinkLeft/Right (eyes closed), mouthSmileLeft/Right (smile), jawOpen (laughing, talking).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import math

import cv2
import numpy as np

from calotype_culling.models import model_path
from calotype_culling.technical import region_sharpness

DETECT_EDGE = 960          # detection runs on this size (faces ≥ ~20 px still found)
MIN_SCORE = 0.75
CROP_MARGIN = 0.45         # context around the face box for the landmarker


@dataclass
class Face:
    box: tuple[int, int, int, int]        # x, y, w, h in preview pixels
    score: float
    rel_size: float                       # face area / image area
    sharpness: float
    eyes_closed: float | None = None      # 0 open … 1 closed (max of both eyes)
    smile: float | None = None            # 0 … 1
    mouth_open: float | None = None       # 0 … 1
    looking_down: float | None = None     # 0 … 1, gaze below the camera (eyeLookDown*)
    head_pitch: float | None = None       # degrees from the face's transformation matrix
    blendshapes: dict[str, float] = field(default_factory=dict)

    @property
    def laughing_closed_eyes(self) -> bool:
        """Closed eyes while laughing: a moment, not a mistake."""
        return (self.eyes_closed or 0) > 0.5 and (self.smile or 0) > 0.5


class FaceAnalyzer:
    def __init__(self) -> None:
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path("yunet")), "", (DETECT_EDGE, DETECT_EDGE), MIN_SCORE, 0.3, 50
        )
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path("face_landmarker"))),
            output_face_blendshapes=True,
            # head pose: separates "eyes closed" from "head and eyes lowered"
            output_facial_transformation_matrixes=True,
            num_faces=1,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> FaceAnalyzer:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def detect(self, rgb: np.ndarray) -> list[tuple[tuple[int, int, int, int], float]]:
        h, w = rgb.shape[:2]
        scale = DETECT_EDGE / max(h, w)
        small = cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
        self._detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, found = self._detector.detect(bgr)
        out = []
        for row in found if found is not None else []:
            x, y, bw, bh = (row[:4] / scale).round().astype(int)
            out.append(((int(x), int(y), int(bw), int(bh)), float(row[-1])))
        return out

    def _expression(
        self, rgb: np.ndarray, box: tuple[int, int, int, int]
    ) -> tuple[dict[str, float], float | None]:
        import mediapipe as mp

        x, y, bw, bh = box
        mx, my = int(bw * CROP_MARGIN), int(bh * CROP_MARGIN)
        h, w = rgb.shape[:2]
        crop = rgb[max(0, y - my): min(h, y + bh + my), max(0, x - mx): min(w, x + bw + mx)]
        if crop.size == 0:
            return {}, None
        if max(crop.shape[:2]) < 192:  # tiny face: upscale so the landmarker can read it
            f = 192 / max(crop.shape[:2])
            crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop))
        result = self._landmarker.detect(image)
        if not result.face_blendshapes:
            return {}, None
        shapes = {c.category_name: float(c.score) for c in result.face_blendshapes[0]}
        pitch = None
        matrices = getattr(result, "facial_transformation_matrixes", None)
        if matrices:
            r = np.asarray(matrices[0])[:3, :3]
            pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
        return shapes, pitch

    def analyze(self, rgb: np.ndarray, gray: np.ndarray) -> list[Face]:
        area = float(rgb.shape[0] * rgb.shape[1])
        faces = []
        for box, score in self.detect(rgb):
            bs, pitch = self._expression(rgb, box)
            face = Face(
                box=box,
                score=score,
                rel_size=(box[2] * box[3]) / area,
                sharpness=region_sharpness(gray, box),
                blendshapes=bs,
            )
            if bs:
                face.eyes_closed = max(bs.get("eyeBlinkLeft", 0.0), bs.get("eyeBlinkRight", 0.0))
                face.smile = (bs.get("mouthSmileLeft", 0.0) + bs.get("mouthSmileRight", 0.0)) / 2
                face.mouth_open = bs.get("jawOpen", 0.0)
                face.looking_down = max(bs.get("eyeLookDownLeft", 0.0), bs.get("eyeLookDownRight", 0.0))
                face.head_pitch = pitch
            faces.append(face)
        return faces
