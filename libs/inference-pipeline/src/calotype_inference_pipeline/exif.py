"""What the camera recorded for a photo (``exif-snapshot-v1``), typed — the one parser of the
snapshot the plugin, the Bridge and folder mode send. Used by the train worker (capture times of
training photos) and the edit plan."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class ExifSnapshot:
    """What the camera recorded for a photo (``exif-snapshot-v1``), typed. The one parser of
    the snapshot the plugin and the Bridge send."""

    capture_time: float | None = None       # seconds; only differences within a shoot matter
    measured_kelvin: float | None = None    # the camera's measured colour temperature
    iso: float | None = None
    shutter_speed: float | None = None      # seconds
    aperture: float | None = None           # f-number
    exposure_bias: float | None = None      # EV

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any] | None) -> ExifSnapshot:
        s = snapshot or {}
        kelvin = _number(s.get("wb_measured_kelvin"))
        return cls(
            capture_time=_capture_time(s.get("date_time_original")),
            measured_kelvin=kelvin if kelvin and kelvin > 0 else None,
            iso=_number(s.get("iso")),
            shutter_speed=_number(s.get("shutter_speed")),
            aperture=_number(s.get("aperture")),
            exposure_bias=_number(s.get("exposure_bias")),
        )

    @property
    def camera_exposure(self) -> list[float] | None:
        """The camera's exposure settings as features: log2 of ISO, shutter time and f-number,
        plus the exposure compensation (0 when not recorded) — None unless ISO, time and
        aperture are known."""
        iso, shutter, aperture = self.iso, self.shutter_speed, self.aperture
        if not iso or not shutter or not aperture or min(iso, shutter, aperture) <= 0:
            return None
        return [math.log2(iso), math.log2(shutter), math.log2(aperture), self.exposure_bias or 0.0]


def _capture_time(raw: Any) -> float | None:
    """Seconds of an ISO 8601 capture time; a time zone offset is ignored."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19]).timestamp()
    except ValueError:
        return None
