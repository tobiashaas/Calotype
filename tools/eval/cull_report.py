"""Culling prototype on a folder of Bridge previews: features, series, baseline decisions.

    python tools/eval/cull_report.py <preview_dir> [--out report.html] [--json features.json]

Writes a local contact sheet (HTML next to the previews by default) grouped by series, with
bucket, score and reasons per photo, and prints timing and a summary. The report links the
preview files; nothing is uploaded anywhere.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from collections import Counter
from pathlib import Path

from tarsier_culling import FaceAnalyzer, analyze, score

BUCKET_COLOR = {"keep": "#2f7d4f", "uncertain": "#b07a12", "reject": "#b3261e"}


def render(previews: Path, out: Path, features, decisions) -> None:
    rows = []
    current = None
    for f, d in zip(features, decisions):
        if d.series != current:
            if current is not None:
                rows.append("</div></section>")
            current = d.series
            label = f"Series {d.series + 1}" + (f" · {d.series_size} shots" if d.series_size > 1 else "")
            rows.append(f"<section><h2>{label}</h2><div class='grid'>")
        faces = f.relevant_faces
        meta = [f"sharpness {f.subject_sharpness:.2f}", f"faces {len(f.faces)}"]
        if f.eyes_closed is not None:
            meta.append(f"eyes closed {f.eyes_closed:.0%}")
        if f.smile is not None:
            meta.append(f"smile {f.smile:.0%}")
        boxes = "".join(
            f"<span class='box' style='left:{x / f.width:.2%};top:{y / f.height:.2%};"
            f"width:{w / f.width:.2%};height:{h / f.height:.2%}'></span>"
            for (x, y, w, h) in (face.box for face in faces)
        )
        src = html.escape((previews / f.name).relative_to(out.parent).as_posix()
                          if (previews / f.name).is_relative_to(out.parent) else (previews / f.name).as_uri())
        rows.append(
            f"<figure class='{d.bucket}'><div class='img'><img loading='lazy' src='{src}'>{boxes}</div>"
            f"<figcaption><b style='color:{BUCKET_COLOR[d.bucket]}'>{d.bucket}</b> "
            f"<span class='score'>{d.score:+.2f}</span> · {html.escape(f.name)}<br>"
            f"<small>{html.escape(d.explanation)}</small><br><small class='meta'>{' · '.join(meta)}</small>"
            "</figcaption></figure>"
        )
    rows.append("</div></section>")
    counts = Counter(d.bucket for d in decisions)
    out.write_text(
        f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Culling report</title>
<style>
body{{font:14px/1.4 system-ui,sans-serif;margin:0;background:#161514;color:#ecebe8}}
header{{padding:16px 20px;border-bottom:1px solid #34312d}} h1{{margin:0;font-size:18px}}
section{{padding:8px 20px}} h2{{font-size:13px;color:#a09c95;font-weight:600;margin:14px 0 8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}}
figure{{margin:0;background:#211f1d;border-radius:8px;overflow:hidden;border:2px solid transparent}}
figure.keep{{border-color:#2f7d4f}} figure.reject{{border-color:#b3261e;opacity:.75}} figure.uncertain{{border-color:#b07a12}}
.img{{position:relative}} img{{display:block;width:100%;height:auto}}
.box{{position:absolute;border:2px solid #5cc28a;border-radius:3px}}
figcaption{{padding:8px 10px}} .score{{color:#a09c95}} .meta{{color:#a09c95}}
</style>
<header><h1>Culling prototype — {len(decisions)} photos</h1>
<div>{counts['keep']} keep · {counts['uncertain']} uncertain · {counts['reject']} reject ·
baseline weights (not yet learned from your ratings)</div></header>
{''.join(rows)}</html>""",
        encoding="utf-8",
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preview_dir", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    previews = sorted(p for p in a.preview_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"})
    out = a.out or a.preview_dir.parent / "cull_report.html"

    t0 = time.perf_counter()
    with FaceAnalyzer() as faces:
        load = time.perf_counter() - t0
        features, times = [], []
        for p in previews:
            t = time.perf_counter()
            features.append(analyze(p, faces))
            times.append(time.perf_counter() - t)
    decisions = score(features)
    render(a.preview_dir, out, features, decisions)
    if a.json:
        a.json.write_text(json.dumps([f.to_dict() for f in features], indent=1), encoding="utf-8")

    counts = Counter(d.bucket for d in decisions)
    n_series = len({d.series for d in decisions})
    multi = sum(1 for s in {d.series for d in decisions} if [d.series for d in decisions].count(s) > 1)
    print(f"{len(previews)} photos · models loaded in {load:.1f} s · "
          f"{1000 * sum(times) / len(times):.0f} ms/photo (max {1000 * max(times):.0f} ms)")
    print(f"faces found: {sum(len(f.faces) for f in features)} in "
          f"{sum(1 for f in features if f.faces)} photos · "
          f"eyes closed (>60%): {sum(1 for f in features if (f.eyes_closed or 0) > 0.6)} · "
          f"laughing with closed eyes: {sum(1 for f in features if f.laughing_closed_eyes)}")
    print(f"series: {n_series} ({multi} with several shots)")
    print(f"buckets: {counts['keep']} keep, {counts['uncertain']} uncertain, {counts['reject']} reject")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
