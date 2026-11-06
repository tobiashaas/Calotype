"""Shared pieces of lrff-eval: slider tolerances, top-level XMP reading, the score table."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

# Slider → (tolerance a photographer would not re-touch, unit)
SLIDERS: dict[str, tuple[float, str]] = {
    "Exposure2012": (0.15, "EV"),
    "Temperature": (150.0, "K"),
    "Tint": (5.0, ""),
    "Contrast2012": (8.0, ""),
    "Highlights2012": (8.0, ""),
    "Shadows2012": (8.0, ""),
    "Whites2012": (8.0, ""),
    "Blacks2012": (8.0, ""),
    "Vibrance": (5.0, ""),
    "Saturation": (5.0, ""),
}

# Windows consoles default to cp1252; never crash on a "±" or "→" in a report line.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ATTR = re.compile(r'crs:(\w+)="([^"]*)"')


def top_description(xmp: str) -> str:
    """Attributes of the first rdf:Description only. Masks, looks and snapshots nest their
    own crs: values (e.g. Exposure2012="0" inside a mask) that are not the photo's settings."""
    start = xmp.find("<rdf:Description")
    if start < 0:
        return xmp
    in_quotes = False
    for i in range(start, len(xmp)):
        c = xmp[i]
        if c == '"':
            in_quotes = not in_quotes
        elif c == ">" and not in_quotes:
            return xmp[start:i]
    return xmp[start:]


def read_xmp(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in _ATTR.findall(top_description(path.read_text(encoding="utf-8", errors="replace"))):
        if k in out:
            continue
        try:
            out[k] = float(v.lstrip("+"))
        except ValueError:
            pass
    return out


def score_table(rows: list[tuple[dict, dict]], train: list[dict], sliders: dict = SLIDERS) -> dict:
    """Print model error vs. 'guess the training mean' per slider; return summary numbers."""
    print(f"{'slider':<16}{'model MAE':>11}{'guess-mean MAE':>16}{'within tol.':>13}   tolerance")
    all_ok = np.ones(len(rows), dtype=bool)
    summary = {"learned": 0, "varying": 0, "per_slider": {}}
    for k, (tol, unit) in sliders.items():
        train_vals = [t[k] for t in train if k in t]
        pairs = [(e[k], p.get(k, np.nan)) for e, p in rows if k in e]
        if not pairs or not train_vals:
            continue
        exp = np.array([a for a, _ in pairs])
        got = np.array([b for _, b in pairs])
        base = np.abs(float(np.mean(train_vals)) - exp)
        err = np.abs(got - exp)
        ok = err <= tol
        if len(pairs) == len(rows):
            all_ok &= ok
        constant = float(np.ptp(train_vals)) == 0.0
        if not constant:
            summary["varying"] += 1
            if np.nanmean(err) < 0.5 * base.mean():
                summary["learned"] += 1
        summary["per_slider"][k] = {"mae": float(np.nanmean(err)), "guess": float(base.mean()),
                                    "within": float(ok.mean())}
        note = " (constant)" if constant else ""
        print(f"{k:<16}{np.nanmean(err):>11.2f}{base.mean():>16.2f}{ok.mean():>12.0%}   ±{tol:g} {unit}{note}")
    summary["all_within"] = float(all_ok.mean())
    print(f"\nphotos with every slider within tolerance: {all_ok.mean():.0%}")
    print(f"sliders learned (error < half of guessing): {summary['learned']} of {summary['varying']}")
    return summary
