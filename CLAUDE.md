# CLAUDE.md — LRFrameFlow

> **Convention:** Keep this file up to date. After every session that changes architecture,
> adds endpoints, or completes a phase — update the relevant sections here and in `TODO.md`.

## Project Overview

LRFrameFlow is an AI-powered Lightroom Classic photo editing system. It uses an async job-orchestration architecture:

1. **LR Plugin** (Lua, `apps/lr-plugin/`) — Lightroom Classic SDK, triggers jobs
2. **Bridge Desktop App** (Tauri/Rust, `apps/bridge/`) — local orchestration layer
3. **API** (FastAPI, `services/api/`) — thin HTTP gateway, returns 202 immediately, no blocking
4. **Workers** (`services/workers/`) — four independent workers: feature, train, inference, cull
5. **Shared Libs** (`libs/`) — domain, persistence, queue, observability, inference-pipeline, edit-serializer, lr-io

---

## Current Implementation Status

| Phase | Status | Summary |
|-------|--------|---------|
| Phase 1 — Domain Foundation | ✅ Done | DB models (Photo, Profile, FeatureVector, EditResult), migrations 002–006, API endpoints |
| Phase 2 — Real Data Flow | ✅ Done | Workers download/upload MinIO, feature extraction, model artifact lifecycle |
| Phase 3 — Real ML Pipeline | ✅ Done | Pillow histogram features (128-dim), Ridge regression, joblib serialization |
| Phase 4 — Production Hardening | ✅ Done | Redis AOF, stuck-job reaper, at-least-once, heartbeat, CI lint+tests, contracts, JSON logs, rate limiting |
| Phase 5 — Bridge & Plugin | 🟡 In progress | Bridge, LR plugin, folder mode (RAW+XMP) done; full stack verified end-to-end on 60 real CR3 (synthetic-rule test 93 % within tolerance); automated end-to-end test in real Lightroom passes (`tools/lr_e2e/run.py`, opt-in automation channel) |
| Phase 6 — Culling | 🟡 In progress | Cull job end to end (plugin menu → Bridge → API → `cull_worker` → collections Keep / Check / Sort out in Lightroom): learns from the stars/flags among the selected photos, else starter rules; verified in Lightroom 15.6 (80 photos in 14 s, 85 % agreement with existing stars). Measured against a photographer's real exports: ROC-AUC 0.654 — see ADR 005 |

See `TODO.md` for the detailed task breakdown.

---

## Monorepo Layout

```
apps/
  bridge/              # Rust workspace: core/ (axum local API, SQLite outbox, previews) + src-tauri/ (desktop shell) + ui/
  lr-plugin/           # LRFrameFlow.lrplugin (Lua 5.1): Train / Apply / Bridge status; tests/run.lua with faked SDK
packages/
  contracts/           # OpenAPI spec + JSON Schemas (source of truth for contracts)
  domain-types/        # Optional shared DTOs (placeholder)
libs/
  domain/              # JobKind, JobStatus, ProfileStatus enums — no infra deps
  persistence/         # SQLAlchemy ORM: Job, Photo, Profile, FeatureVector, EditResult
  queue/               # Redis Lists publisher/consumer + DLQ
  observability/       # get_logger() — stdlib logging wrapper
  inference-pipeline/  # Feature extraction (Pillow) + Ridge model (scikit-learn/joblib)
  edit-serializer/     # internal params ↔ Lightroom develop settings (names, ranges)
  culling/             # culling features (sharpness, faces, expressions, series) + explainable baseline scorer
  lr-io/               # Shared path/I/O helpers (stub)
services/
  api/                 # FastAPI: all routes (photos, profiles, jobs, results)
  workers/
    feature_worker/    # lrff:jobs:feature → extract features → lrff:jobs:inference
    train_worker/      # lrff:jobs:train → train Ridge model → Profile READY
    inference_worker/  # lrff:jobs:inference → run inference → EditResult
    cull_worker/       # lrff:jobs:cull → culling features (cached in photos.analysis) → CullResult
infra/
  compose/             # docker-compose.yml: Postgres 16+pgvector, Redis 7, MinIO
  migrations/          # Alembic migrations (001–012)
docs/
  adr/                 # Architecture Decision Records
  plan/                # mvp.md — phased plan
scripts/
  validate_contracts.py
TODO.md                # Completed + open work items — keep up to date
```

---

## Architecture Principles

- **API is fire-and-forget:** All endpoints return 202. Never add blocking work to the API.
- **Strict module import boundaries** (enforced per ADR-003):
  - `domain` imports nothing
  - `queue` imports: domain, pydantic, redis
  - `persistence` imports: domain, sqlalchemy, psycopg
  - `observability` imports: stdlib only
  - `inference-pipeline` imports: Pillow, numpy, scikit-learn, joblib, opencv-python-headless (YuNet face box) — no DB/Redis; owns the model registry (`models.py`)
  - `services/api` imports: domain, persistence, queue — NOT workers, NOT torch
  - `edit-serializer` imports: stdlib only
  - `culling` imports: inference-pipeline (model registry), numpy, Pillow, opencv-python-headless, mediapipe, scikit-learn — no DB/Redis; models only via the registry (SHA-256, `THIRD_PARTY_MODELS.md`)
  - `services/workers/*` import: domain, persistence, queue, observability, inference-pipeline, edit-serializer; `cull_worker` also culling
  - **Workers CANNOT import `lr_frameflow_api`**
  - **API CANNOT import worker modules**
- **Versioned contracts:** Every queue message and API schema has a `schema_version` field. Never break existing schema versions; add new ones.
- **Tolerant reader:** request models ignore (and log) unknown *optional* fields instead of rejecting them — a newer Bridge must work with an older server. New *required* fields need a new schema version. (Found when an updated Bridge sent `lr_metadata` to a not-yet-restarted API: every upload failed with 422.)
- **Idempotency:** Use the `idempotency_key` DB column (unique partial index) for safe retries.
- **Photo upload is idempotent:** Uploading the same `lr_catalog_uuid` twice returns the existing record.

---

## Key Files

| File | Purpose |
|------|---------|
| `libs/domain/src/lr_frameflow_domain/jobs.py` | `JobKind` & `JobStatus` enums |
| `libs/domain/src/lr_frameflow_domain/profiles.py` | `ProfileStatus` enum |
| `libs/persistence/src/lr_frameflow_persistence/models.py` | All SQLAlchemy models |
| `libs/persistence/src/lr_frameflow_persistence/repositories/` | One repo file per model |
| `libs/inference-pipeline/src/lr_frameflow_inference_pipeline/features.py` | `extract_features()` — 128-dim histogram |
| `libs/inference-pipeline/src/lr_frameflow_inference_pipeline/model.py` | `train_model()` / `run_inference()` |
| `libs/edit-serializer/src/lr_edit_serializer/sliders.py` | `from_lightroom()` / `to_lightroom()` — LR names, ranges, RAW vs JPEG white balance |
| `libs/queue/src/lr_frameflow_queue/envelope.py` | `JobEnvelopeV1` — canonical queue message |
| `libs/queue/src/lr_frameflow_queue/constants.py` | Queue keys: `lrff:jobs:train`, `lrff:jobs:feature`, `lrff:jobs:inference` |
| `libs/queue/src/lr_frameflow_queue/publisher.py` | `enqueue()`, `forward_to_inference()` |
| `libs/queue/src/lr_frameflow_queue/consumer.py` | `blpop_envelope()`, `push_dead_letter()` |
| `services/api/src/lr_frameflow_api/main.py` | FastAPI app + all routes |
| `services/api/src/lr_frameflow_api/schemas.py` | Pydantic request/response models |
| `services/api/src/lr_frameflow_api/deps.py` | FastAPI dependencies (DB session, publisher, S3) |
| `services/api/src/lr_frameflow_api/storage.py` | boto3 MinIO helper |
| `packages/contracts/openapi/bridge-api.yaml` | OpenAPI spec (Bridge ↔ API contract) |
| `packages/contracts/openapi/plugin-bridge-api.yaml` | OpenAPI spec (LR plugin ↔ Bridge, local, `X-LRFF-Token`) |
| `apps/bridge/core/src/outbox.rs` | Background loop: preview → upload → submit job → poll → map results |
| `apps/bridge/core/src/server.rs` | Local API for the plugin (127.0.0.1:47600) |
| `apps/bridge/core/src/preview.rs` | Unedited preview: smallest embedded RAW JPEG ≥ 1200 px (else largest) / original JPEG/TIFF, orientation applied |
| `apps/lr-plugin/LRFrameFlow.lrplugin/BridgeClient.lua` | Plugin → Bridge HTTP, reads `bridge.json` |
| `apps/bridge/core/src/xmp.rs` | Read/write Adobe `crs:` XMP sidecars (ProcessVersion 15.4, `lrff:Profile`) |
| `apps/bridge/core/src/bin/folder.rs` | `lrff-folder train/apply/cull/profiles` — folder mode without Lightroom |
| `libs/culling/src/lr_frameflow_culling/scoring.py` | Series + explainable baseline (keep/uncertain/reject with reasons) |
| `libs/culling/src/lr_frameflow_culling/identity.py` | SFace face embeddings + grouping photos by person |
| `libs/inference-pipeline/src/lr_frameflow_inference_pipeline/straighten.py` | Tilt from the photo's own lines (keystone-aware) + Lightroom crop keys |
| `libs/culling/src/lr_frameflow_culling/cull.py` | `cull()`: learned from decided photos (≥ 8 per class) else rules; `decision_from_metadata` |
| `apps/lr-plugin/LRFrameFlow.lrplugin/CullPhotos.lua` | Menu: sort selected photos into collections (stars/flags untouched) |
| `tools/lr_e2e/cull_check.py` | Culling end-to-end in a real Lightroom (collections, nothing else touched, cleanup) |
| `tools/lr_e2e/straighten_check.py` | Straighten end-to-end in a real Lightroom (angle + crop arrive, own crops stay, restore) |
| `tools/lrff_eval/cull_report.py` | Culling prototype on a preview folder → local HTML contact sheet + timing |
| `THIRD_PARTY_MODELS.md` | Every downloaded model with license and SHA-256 — permissive only |
| `tools/lrff_eval/synthetic.py` | Synthetic-rule test: make rule XMPs, score predictions vs. rule and vs. guessing |
| `apps/lr-plugin/LRFrameFlow.lrplugin/ApplyProfile.lua` | Edit flow in Lightroom, `applyDevelopSettings` in one transaction |
| `packages/contracts/json-schema/job-envelope-v1.schema.json` | Queue envelope schema |
| `packages/contracts/json-schema/photo-upload-v1.schema.json` | Photo upload metadata schema |
| `infra/compose/docker-compose.yml` | Local infra (Postgres, Redis, MinIO) |
| `infra/compose/.env` | Local port overrides (Postgres 5433, MinIO 9100) |
| `infra/migrations/versions/` | Migrations 001–012 (010 job progress + unique edit results, 011 `photos.analysis`, 012 `cull_results`) |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/v1/photos` | Upload JPEG preview + metadata (idempotent by `lr_catalog_uuid`) |
| GET | `/v1/profiles` | List all profiles |
| GET | `/v1/profiles/{id}` | Get single profile with status |
| POST | `/v1/jobs/train` | Enqueue train job (creates Profile in DRAFT, returns `profile_id`) |
| POST | `/v1/jobs/edit` | Enqueue edit job (profile must be READY, photo_ids must exist) |
| GET | `/v1/jobs/{id}` | Get job status snapshot (incl. `profile_id`, short `failure_reason`) |
| GET | `/v1/jobs/{id}/result` | Get edit results (only when job is COMPLETED) |
| POST | `/v1/jobs/cull` | Enqueue cull job (`cull-request-v1`: photo_ids; photos with stars/flags teach the scorer) |
| GET | `/v1/jobs/{id}/cull-result` | Culling decisions (bucket keep/uncertain/reject, score, reason, method) |

---

## Job Pipeline

```
Edit job:   API → lrff:jobs:feature → feature_worker → lrff:jobs:inference → inference_worker
Train job:  API → lrff:jobs:train   → train_worker   → COMPLETED
Cull job:   API → lrff:jobs:cull    → cull_worker    → CullResult → COMPLETED
```

Train flow detail:
1. API creates Profile (DRAFT) + Job, enqueues to `lrff:jobs:train`
2. `train_worker`: Profile → TRAINING; per photo: maps `lr_develop_settings` (LR names) to internal params via `from_lightroom`, computes the feature vector if missing (download preview from MinIO); photos without usable preview or settings are skipped; needs ≥ 3 usable photos; trains Ridge model, saves `.joblib` to MinIO, Profile → READY

Edit flow detail:
1. API validates Profile is READY + all photo_ids exist, enqueues to `lrff:jobs:feature`
2. `feature_worker`: downloads JPEG from MinIO, extracts the feature vectors of every supported version, saves FeatureVector (skips photos whose preview is missing/undecodable — never stores zero vectors); measures the tilt once per photo (`photos.analysis.straighten`); forwards to `lrff:jobs:inference`
3. `inference_worker`: loads `.joblib` from MinIO (missing artifact → job FAILED), predicts 10 params per photo, converts to LR develop settings via `to_lightroom` (clamped, LR key names), adds the style layer and — if the request has `straighten: true` and the photo has clear reference lines — Lightroom crop keys; upserts EditResult (one per photo and job); photos without feature vector get no result
4. Workers touch `jobs.last_progress_at` per photo; the reaper re-runs only jobs without progress for 10 min, each kind from its first queue (edit → feature, train → train)

On error at any stage: Job → FAILED, envelope pushed to `{queue}:dlq`.

---

## ML Pipeline

- **Feature versions** (one vector per photo *and* version, migration 009; `compute_features(bytes, version)`):
  - `histogram-v1`: 128 floats — R/G/B/Brightness histograms, 32 bins each (old profiles)
  - `histstats-face-v2` (**current**): v1 + 20 tone/color stats + 5 face values (YuNet largest face: brightness, color) = 153 floats
- **Models** (artifact records `feature_version`; inference uses exactly that version, refuses wrong vector sizes):
  - v1: `MultiOutputRegressor(Ridge)` + `StandardScaler` (`ridge_v1`)
  - v2: `HistGradientBoostingRegressor` per slider (`gbr_v2`); < 30 photos → Ridge (`ridge_v2`)
- **Benchmark** (1,837 edited Canon R6 photos from another tool, 367 held out, end-to-end through the pipeline): v1 → v2: exposure MAE 0.33 → 0.20 EV, temperature 258 → 163 K, all sliders within tolerance 14 % → 32 % (`tools/lrff_eval/holdout.py`, `model_lab.py`)
- **More internal yardsticks** (2026-11-07, other tools' edits, never shipped): through real Lightroom (`tools/lr_e2e/train_eval.py`) R6 33 % all-within (exposure 54 %, temperature 58 %); wedding (Aftershoot look, 620/155) 54 %; kindergarten portraits vs. Neurapix (495/123, edits exported from the catalog, `lrff-folder train --sidecars`) 49 %, exposure 88 %
- **Straighten** (`straighten.py`): only nearly plumb verticals and long horizons vote, keystone modelled (lean grows with distance from the centre, tilt = value at the centre); < 5 agreeing lines or no lines on both sides → no rotation. Crop = largest aspect-keeping rectangle, stored like Lightroom: corners of the rotated rectangle in the unrotated sensor frame (verified in Lightroom via `straighten_probe`). Rotates 3–6 % of event/wedding photos; there median 0.2–0.3° from another tool's angle (never rotating: 0.6–0.7°). Plugin keeps photos with an own crop.
- **Style layer:** profile `base_preset` adds the look (curve, HSL, grading …) on top of each prediction (`lr_edit_serializer.style`)
- **10 LR params predicted:** `exposure, temp, tint, contrast, highlights, shadows, whites, blacks, vibrance, saturation`
- **Minimum:** train worker refuses < 3 usable photos (Profile FAILED); `run_inference` raises on unreadable artifacts instead of returning zeros (zeros would reset the user's photos)
- **Output names:** model works with internal names (`exposure`, `temp` …); `libs/edit-serializer` maps to/from LR (`Exposure2012`, `Temperature`/`IncrementalTemperature` …)
- **Artifact path:** `models/{profile_id}/model-{feature_version}.joblib` in the S3 bucket

---

## Tech Stack

| Layer | Tech |
|-------|------|
| API | FastAPI 0.115+, Pydantic 2.10+, Uvicorn 0.32+ |
| Database | PostgreSQL 16 + pgvector, SQLAlchemy 2.0+, Alembic 1.14+ |
| Queue | Redis 7, redis-py 5.2+ |
| Object Storage | S3-compatible: RustFS 1.0 (Apache-2.0) in compose (MinIO publishes no community images anymore), boto3 1.35+ |
| Workers | Python 3.11+, blocking BLPOP loop |
| ML | scikit-learn 1.4+, Pillow 10+, numpy 1.26+, joblib 1.3+ |
| Desktop Bridge | Rust (axum 0.8, rusqlite, reqwest, image) + Tauri 2, static HTML/JS UI |
| LR Plugin | Lightroom Classic SDK (Lua) |
| Linting | Ruff 0.8+ |
| Testing | pytest 8+ |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |

---

## Local Development

```bash
# Start infrastructure
cp infra/compose/env.example infra/compose/.env
# Edit .env to set port overrides if needed (Postgres 5433, MinIO 9100/9101)
cd infra/compose && docker compose -p lrframeflow up -d

# Install Python libs (order matters due to dependencies)
pip install -e libs/domain
pip install -e libs/queue
pip install -e libs/persistence
pip install -e libs/observability
pip install -e libs/inference-pipeline
pip install -e libs/edit-serializer
pip install -e services/api
pip install -e services/workers/feature_worker
pip install -e services/workers/train_worker
pip install -e services/workers/inference_worker

# Run database migrations
cd infra/migrations
DATABASE_URL="postgresql+psycopg://lrframeflow:lrframeflow@127.0.0.1:5433/lrframeflow" alembic upgrade head

# Start API
cd services/api
DATABASE_URL="postgresql+psycopg://lrframeflow:lrframeflow@127.0.0.1:5433/lrframeflow" \
  uvicorn lr_frameflow_api.main:app --reload

# Windows: always use 127.0.0.1, never "localhost" (IPv6 ::1 is tried first and Docker's
# port forward hangs there → ~21 s per connection). Code defaults follow this.

# Validate contracts (also runs in CI)
python scripts/validate_contracts.py

# Bridge (Rust; rustup in ~/.cargo/bin)
cd apps/bridge
cargo test -p lrff-bridge-core                               # fast, no Tauri
cargo run -p lrff-bridge-core --bin lrff-bridge-headless     # bridge without window
npm install && npm run dev                                   # desktop app
cargo run --release -p lrff-bridge-core --example preview -- <out> <raw files>  # preview check on real RAWs

# Lightroom plugin tests (LuaJIT = Lua 5.1 like Lightroom; `scoop install luajit`)
luajit apps/lr-plugin/tests/run.lua
```

---

## CI

Nine jobs on push/PR to `main`:
1. **contracts** — validates OpenAPI spec + all JSON schemas + examples
2. **lint** — Ruff check across all Python source dirs
3. **inference-pipeline** — `pytest libs/inference-pipeline/tests/`
4. **edit-serializer** — `pytest libs/edit-serializer/tests/`
5. **api-tests** — `pytest services/api/tests/` (mock-based, no Postgres needed)
6. **worker-tests** — `pytest services/workers/train_worker/tests/` (mock-based, no DB/S3)
7. **bridge-core** — `cargo fmt --check`, `clippy -D warnings`, `cargo test -p lrff-bridge-core` (incl. end-to-end against a fake API)
8. **lr-plugin** — `luajit apps/lr-plugin/tests/run.lua` (Lightroom SDK faked)
9. **culling** — `pytest libs/culling/tests/` (synthetic images, no models needed)

---

## ADRs (key decisions)

| ADR | Decision |
|-----|----------|
| 001 | Redis Lists for async queuing; API returns 202 immediately |
| 002 | Tauri (Rust) for Bridge instead of Electron |
| 003 | Redis DLQ per primary queue; strict module import matrix |
| 004 | Bridge = local Rust/axum service on 127.0.0.1 with SQLite outbox; LR plugin = UI, talks only to Bridge; model input = unedited image (embedded RAW JPEG / original) |

Full docs in `docs/adr/`.

---

## Environment Variables

Key vars (see `infra/compose/env.example` for full list):

| Variable | Default | Used by |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+psycopg://lrframeflow:lrframeflow@127.0.0.1:5433/lrframeflow` | API, workers, migrations |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | API, workers |
| `S3_ENDPOINT` | `http://127.0.0.1:9100` | workers, API |
| `S3_BUCKET` | `lrff-photos` | workers, API |
| `S3_ACCESS_KEY` | `minio` | workers, API |
| `S3_SECRET_KEY` | `miniosecret_changeme` | workers, API |
| `LOG_FORMAT` | `json` | all services — set to `text` for human-readable local output |
| `RATE_LIMIT_REQUESTS` | `60` | API — max requests per window per IP on job endpoints |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | API — sliding window length in seconds |
| `MAX_QUEUE_DEPTH` | `500` | API — max queue length before 429 backpressure |
