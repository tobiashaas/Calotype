"""White balance: keep the camera's ("As shot") or set an own Kelvin — per profile or per photo?

    python tools/eval/wb_decision.py --db postgresql+psycopg://user:pw@127.0.0.1:5433/db \
        --train-profile "Hochzeit Holdout (ohne …)" --all-profile "Hochzeit 2015–2019"

Reads a database the API wrote (read-only): the training photos of one train job (`--train-profile`,
the newest train job with that profile name) and, as the unseen photos, those of another train job
(`--all-profile`) that are not in the first — e.g. three weddings held out. Trains the current model
on the first set exactly as the train worker does (`training_target`, per-photo as-shot flags) and
scores the white balance on the unseen photos for

  * profile   — the old rule (#23): the whole profile keeps the camera's white balance when at least
                ``AS_SHOT_SHARE`` of its training photos did;
  * predict   — always the predicted Kelvin;
  * per photo — keep As shot when the prediction is within T mired of the camera's Kelvin.

Truth is each unseen photo's own settings. A photo whose truth is As shot carries its camera Kelvin, so
"keep" is exact for it; for a photo the photographer gave an own white balance the camera Kelvin is
unknown here, so the decision compares with the training photos' median camera Kelvin (at apply time
in Lightroom the photo is untouched and its camera Kelvin is known — this understates "per photo").
"""

from __future__ import annotations

import argparse
import json
import statistics as st

from sqlalchemy import create_engine, text

from calotype_edit_serializer import training_target
from calotype_inference_pipeline import CURRENT_FEATURE_VERSION, train_for_version
from calotype_inference_pipeline import model as model_module
from calotype_inference_pipeline.model import AS_SHOT_SHARE, run_inference

WITHIN_K = 150.0


def _photo_ids(conn, profile_name: str) -> list[str]:
    row = conn.execute(text(
        "select payload from jobs where kind='train' and payload->>'profile_name' = :n "
        "order by created_at desc limit 1"), {"n": profile_name}).first()
    if row is None:
        raise SystemExit(f"no train job for profile {profile_name!r}")
    return [str(p) for p in row[0]["photo_ids"]]


def _load(conn, ids: list[str]) -> dict[str, tuple[dict, list[float]]]:
    rows = conn.execute(text(
        "select p.id::text, p.lr_develop_settings, f.vector::text from photos p "
        "join feature_vectors f on f.photo_id = p.id and f.model_version = :v "
        "where p.id::text = any(:ids)"), {"v": CURRENT_FEATURE_VERSION, "ids": ids}).all()
    return {pid: (settings, json.loads(vec)) for pid, settings, vec in rows}


def _score(rows: list[tuple[float, float]]) -> tuple[float, float]:
    errs = [abs(p - t) for p, t in rows]
    return 100.0 * sum(e <= WITHIN_K for e in errs) / len(errs), st.mean(errs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--train-profile", required=True)
    ap.add_argument("--all-profile", required=True)
    ap.add_argument("--mired", type=float, nargs="+", default=[10, 15, 20, 25, 30, 40])
    a = ap.parse_args()

    with create_engine(a.db).connect() as conn:
        train_ids = _photo_ids(conn, a.train_profile)
        unseen_ids = sorted(set(_photo_ids(conn, a.all_profile)) - set(train_ids))
        train, unseen = _load(conn, train_ids), _load(conn, unseen_ids)

    targets = [(training_target(s, "raw"), v) for s, v in train.values()]
    targets = [(t, v) for t, v in targets if "temp" in t.sliders]
    flags = [t.as_shot for t, _ in targets]
    share = sum(flags) / len(flags)
    print(f"training photos {len(targets)} (as shot {share:.0%}), unseen photos {len(unseen)}")
    model = train_for_version([v for _, v in targets], [t.sliders for t, _ in targets],
                              CURRENT_FEATURE_VERSION, as_shot=flags)
    camera_median = st.median(t.sliders["temp"] for t, _ in targets if t.as_shot)

    cases = []  # (truth Kelvin, truth as shot?, camera Kelvin or None, predicted Kelvin)
    model_module.AS_SHOT_MIRED = -1.0  # never keep: raw prediction
    for settings, vec in unseen.values():
        truth = training_target(settings, "raw")
        if "temp" not in truth.sliders:
            continue
        pred = run_inference(model, vec)["temp"]
        cases.append((truth.sliders["temp"], truth.as_shot, truth.sliders["temp"] if truth.as_shot else None, pred))
    n_as_shot = sum(c[1] for c in cases)
    print(f"scored {len(cases)} unseen photos, {n_as_shot / len(cases):.0%} of them as shot by the photographer\n")

    def decide(keep) -> tuple[float, float, float, float]:
        rows, kept, right = [], 0, 0
        for truth, truth_as_shot, camera, pred in cases:
            ref = camera if camera is not None else camera_median
            k = keep(pred, ref)
            kept += k
            right += (k == truth_as_shot)
            rows.append((ref if k else pred, truth))
        within, mae = _score(rows)
        return within, mae, 100.0 * kept / len(cases), 100.0 * right / len(cases)

    print(f"{'rule':<22}{'±150 K':>8}{'MAE K':>8}{'kept':>8}{'right':>8}")
    results = {
        "profile (old #23)": decide(lambda p, r: share >= AS_SHOT_SHARE),
        "predict always": decide(lambda p, r: False),
    }
    for m in a.mired:
        results[f"per photo {m:g} mired"] = decide(
            lambda p, r, m=m: abs(1e6 / max(p, 1) - 1e6 / max(r, 1)) <= m)
    for name, (within, mae, kept, right) in results.items():
        print(f"{name:<22}{within:>7.1f}%{mae:>8.0f}{kept:>7.1f}%{right:>7.1f}%")
    print("\nkept = share given the camera's white balance; right = keep/own decision equals the photographer's")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
