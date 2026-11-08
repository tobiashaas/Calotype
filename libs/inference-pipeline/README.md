# calotype-inference-pipeline

Image features, models and straightening — pure computation, no DB, no Redis.

| Module | Contents |
|---|---|
| `__init__.py` | `compute_features(bytes, version)` — one entry point for every feature version |
| `features.py` | `histogram-v1`: 128 floats (R/G/B/brightness histograms, 32 bins) |
| `features_v2.py` | `histstats-face-v2` (current): v1 + 20 tone/color stats + 5 face values = 153 floats |
| `faces.py` | Largest face (YuNet) for the face values |
| `model.py` | `train_model_v2()` / `run_inference()` (`train_model()` = v1): boosting per slider (`gbr_v2`), < 30 photos Ridge; the artifact records its feature version; unreadable artifacts raise instead of returning zeros |
| `models.py` | Model registry: downloads permissively licensed models once, checks SHA-256 ([THIRD_PARTY_MODELS.md](../../THIRD_PARTY_MODELS.md)); cache in `CALOTYPE_MODEL_DIR` |
| `straighten.py` | `estimate_tilt()` from nearly plumb verticals and long horizons (keystone-aware, ≥ 5 agreeing lines on both sides) and `crop_settings()` — Lightroom's crop keys for the largest aspect-keeping rectangle |

```bash
pip install -e "libs/inference-pipeline[dev]"
pytest libs/inference-pipeline/tests
```

Benchmarks and their caveats (random vs. contiguous splits) are in [`CLAUDE.md`](../../CLAUDE.md#ml-pipeline).
