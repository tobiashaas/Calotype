# culling

Features for photo selection and an explainable starter scorer
([ADR 005](../../docs/adr/005-culling-architecture.md)). Pure image analysis on the
Bridge preview (≤ 1200 px, upright, unedited) — no DB, no Redis.

| Module | Contents |
|---|---|
| `technical.py` | Sharpness (Laplacian variance, fixed measuring size, small regions never upscaled), exposure/clipping, dHash |
| `faces.py` | YuNet finds faces, MediaPipe reads eyes closed, smile, mouth open per face (blendshapes) |
| `analyze.py` | `PhotoFeatures` per photo: relevant faces, subject sharpness, clipping on the face |
| `scoring.py` | Bursts (consecutive similar images), starter scorer with reasons, buckets keep/uncertain/reject |
| `learned.py` | Learned scorer: logistic regression over the same features, trained from decisions (stars/picks); explanations describe the photo ("+ large face; + eyes open") |
| `cull.py` | `cull()`: learned scorer when there are ≥ 8 decided photos per class, else the rules; `decision_from_metadata` (pick flag, else 4–5 ★ keep / 1–3 ★ not) |
| `identity.py` | SFace face embeddings, groups photos by person |
| `models.py` | Re-export of the model registry from `inference-pipeline` (SHA-256, [THIRD_PARTY_MODELS.md](../../THIRD_PARTY_MODELS.md)) |

Rules of the starter scorer (the weights are later learned from your stars/flags):

- Technical flaws are evidence, not a veto — a strong expression halves the blur penalty.
- Laughing with closed eyes is a moment, not a mistake.
- Sharpness counts relative to the shoot (equal values = equal rank, from 5 photos up).
- A bright window in the background is not a flaw; a blown-out face is.
- In a burst the best image wins; the others land in "uncertain", not in the trash.

```bash
pip install -e libs/culling
python tools/eval/cull_report.py <preview-folder>   # contact sheet (HTML, local) + timings
pytest libs/culling/tests
```

Benchmark against another tool's cull (1,837 photos, 367 held out for testing): starter weights
ROC-AUC 0.42 (worse than chance for this shoot), learned weights 0.74, agreement
46 % → 71 % (`tools/eval/cull_learn.py`). Taste cannot be prescribed — it is learned.

Against a photographer's real choice (exports in the catalog, kindergarten shoots, leave-one-group-out,
`tools/eval/cull_groups.py`): rules ROC-AUC 0.53, learned 0.654 with series-relative expression
features. A few ratings inside the culled shoot help little (10+10: 0.56); decisions from other
shoots help more — hence the planned culling profiles.

Measured on 60 Canon CR3 previews (business shoot): ~130 ms per photo on CPU,
models load in ~2 s.
