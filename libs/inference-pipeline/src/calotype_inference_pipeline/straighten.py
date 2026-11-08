"""Straighten: level a photo only when its own lines say how — otherwise leave it alone.

Long straight segments (OpenCV line segment detector) that are nearly vertical (walls, door
frames, poles) or nearly horizontal and very long (horizon) vote for the tilt, corrected for
keystone (see `tilt_from_segments`). Fewer than MIN_LINES agreeing lines → no rotation: in
portraits a hat brim or a jacket edge is not a reference, and tilting them "level" makes the photo worse (found on real shoots: a kiss photo would have been
turned by 5.8°).

Measured on 460 event photos against another tool's straightening: with ≥ 5 agreeing lines the
angles match closely (median difference 0.35–0.57°); the camera's roll sensor did not match at
all. The photographer's own corrections mostly reset portrait tilts to 0, which is the default
here.

`Tilt.crop_angle` is Lightroom's `CropAngle` in degrees (0 = leave as is); `crop_settings` turns
it into the full set of Lightroom crop keys.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

MAX_TILT = 4.0           # only lines within this many degrees of level/plumb vote
MEASURE_EDGE = 1024      # long edge the photo is measured at
MIN_VERTICAL = 0.12      # vertical segments: minimum length as a share of the diagonal
MIN_HORIZONTAL = 0.30    # horizontal segments must be much longer (perspective tilts short ones)
AGREE = 0.75             # votes within ± this of the median agree
MIN_LINES = 5            # fewer agreeing lines → leave the photo as it is


@dataclass(frozen=True)
class Tilt:
    crop_angle: float    # Lightroom CropAngle that levels the photo (0 = no change)
    lines: int           # agreeing reference lines (0 when there is no clear reference)
    spread: float        # weighted std of the agreeing votes in degrees (lower = cleaner)

    @property
    def confident(self) -> bool:
        return self.lines >= MIN_LINES


def _gray(image: Image.Image) -> np.ndarray:
    img = image.convert("L")
    scale = MEASURE_EDGE / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


def _segments(gray: np.ndarray) -> np.ndarray:
    lines = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    return np.zeros((0, 4)) if lines is None else lines.reshape(-1, 4).astype(float)


def _fit(dev: np.ndarray, u: np.ndarray, w: np.ndarray, is_v: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Weighted least squares dev = tilt + slope·u (slope only for verticals); returns
    tilt, slope and the residuals. Horizontal lines (u = 0 for them) measure the tilt directly."""
    X = np.column_stack([np.ones_like(dev), np.where(is_v, u, 0.0)])
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(X * sw[:, None], dev * sw, rcond=None)
    return float(coef[0]), float(coef[1]), dev - X @ coef


def tilt_from_segments(segments: np.ndarray, width: int, height: int) -> Tilt:
    """The tilt from line segments (x1, y1, x2, y2) of an upright photo of this size.

    A camera pointing slightly up or down makes verticals lean outwards the further they are
    from the centre (keystone), so a door frame at the edge says little about the tilt. Each
    vertical's deviation is modelled as tilt + slope · (horizontal position from the centre);
    the tilt is the value at the centre. Without lines on both sides (or a long horizon) the
    slope cannot be told apart from the tilt, so the photo is left alone.
    """
    if len(segments) == 0:
        return Tilt(0.0, 0, 0.0)
    diag = float(np.hypot(width, height))
    dx, dy = segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1]
    length = np.hypot(dx, dy)
    theta = (np.degrees(np.arctan2(dy, dx)) + 90.0) % 180.0 - 90.0      # (-90, 90]
    vertical = (np.abs(np.abs(theta) - 90.0) <= MAX_TILT) & (length >= MIN_VERTICAL * diag)
    horizontal = (np.abs(theta) <= MAX_TILT) & (length >= MIN_HORIZONTAL * diag)
    voting = vertical | horizontal
    if voting.sum() < MIN_LINES:
        return Tilt(0.0, int(voting.sum()), 0.0)
    dev = np.where(horizontal, theta, np.where(theta > 0, theta - 90.0, theta + 90.0))[voting]
    u = ((segments[:, 0] + segments[:, 2]) / 2 / width - 0.5)[voting]
    w, is_v = length[voting], vertical[voting] & ~horizontal[voting]

    keep = np.ones(len(dev), bool)
    for _ in range(3):                        # drop lines that do not fit (railings, arms …)
        if keep.sum() < MIN_LINES:
            return Tilt(0.0, int(keep.sum()), 0.0)
        tilt, slope, res = _fit(dev[keep], u[keep], w[keep], is_v[keep])
        new = np.zeros_like(keep)
        new[np.where(keep)[0]] = np.abs(res) <= AGREE
        if (new == keep).all():
            break
        keep = new
    n = int(keep.sum())
    if n < MIN_LINES:
        return Tilt(0.0, n, 0.0)
    tilt, slope, res = _fit(dev[keep], u[keep], w[keep], is_v[keep])
    uv = u[keep & is_v]
    has_horizon = bool((keep & ~is_v).any())
    both_sides = len(uv) > 0 and uv.min() < -0.1 and uv.max() > 0.1
    if not (has_horizon or both_sides) or abs(tilt) > MAX_TILT:
        return Tilt(0.0, 0, 0.0)      # lines, but no usable reference
    spread = float(np.sqrt(np.average(res**2, weights=w[keep])))
    return Tilt(round(tilt, 2), n, round(spread, 2))


def estimate_tilt(image: Image.Image) -> Tilt:
    gray = _gray(image)
    return tilt_from_segments(_segments(gray), gray.shape[1], gray.shape[0])


def crop_settings(crop_angle: float, sensor_width: int, sensor_height: int) -> dict[str, float | bool]:
    """Lightroom crop keys for a straighten angle: the largest crop with the photo's aspect ratio
    inside the rotated photo — what Lightroom's Develop module sets itself.

    Lightroom stores the top-left and bottom-right corners of the rotated crop rectangle,
    normalized to the unrotated *sensor* image (not the displayed orientation; the angle keeps
    its sign either way). Checked against Lightroom (3° on 6000×4000: left 0.052637, top 0) and
    against 1,335 straightened photos of another tool that match exactly.
    """
    if not crop_angle:
        return {"CropAngle": 0.0, "CropLeft": 0.0, "CropTop": 0.0, "CropRight": 1.0, "CropBottom": 1.0}
    w, h = float(sensor_width), float(sensor_height)
    t = math.radians(crop_angle)
    c, s = math.cos(t), math.sin(t)
    k = min(w / (w * c + h * abs(s)), h / (w * abs(s) + h * c))
    half_w, half_h = k * w / 2, k * h / 2
    x = -half_w * c + half_h * s        # top-left corner, relative to the centre
    y = -half_w * s - half_h * c
    return {
        "CropAngle": round(crop_angle, 2),
        "CropLeft": round(0.5 + x / w, 6),
        "CropTop": round(0.5 + y / h, 6),
        "CropRight": round(0.5 - x / w, 6),
        "CropBottom": round(0.5 - y / h, 6),
        "HasCrop": True,
    }
