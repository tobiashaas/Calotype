# MVP Plan — Tarsier

**As of:** 2026-05-15  
**Goal:** A fully working system from the LR plugin to writing the develop settings back, with a real ML pipeline — built step by step, never blind.

---

## Guiding principles

- **Domain first.** The data model exists before any code. Everything else derives from it.
- **End-to-end before perfection.** Every phase ends with a runnable, testable system — no dead code.
- **Stubs are fine, gaps are not.** A stub that sends real data through real infrastructure is better than perfect code that is connected to nothing.
- **Contracts are sacred.** JSON Schema and OpenAPI are updated before the implementation, not after.

---

## Domain model (decided, applies to all phases)

```
Photo
├── id                    UUID, assigned internally
├── lr_catalog_uuid       String — assigned by LR Classic, stable identifier
├── s3_key                String — path of the JPEG preview in MinIO
├── exif_snapshot         JSONB — camera, ISO, exposure, focal length etc.
├── lr_develop_settings   JSONB — current LR settings at export (baseline)
├── feature_vector_id     → FeatureVector (nullable, null until extracted)
└── created_at

FeatureVector
├── id                    UUID
├── photo_id              → Photo
├── model_version         String — versioning of the extraction algorithm
├── vector                pgvector — dimension depends on model_version
└── created_at

Profile
├── id                    UUID
├── name                  String
├── genre                 String (wedding, portrait, landscape, …)
├── format_type           "raw" | "jpeg_tiff"
├── color_type            "color" | "bw"
├── status                "draft" | "training" | "ready" | "failed"
├── version               Int — incremented on retraining
├── base_preset           JSONB — optional LR preset as a starting point
├── model_artifact_key    String nullable — S3 key of the stored model weights
├── lr_output_keys        JSONB — which LR parameters this profile predicts
│                                 e.g. ["exposure", "contrast", "highlights", ...]
├── failure_reason        String nullable
└── created_at / updated_at

Job (extension of existing)
└── profile_id            → Profile (nullable, required for edit jobs)
```

**Key decisions:**
- Feature vectors are **per photo, independent of profiles** — compute once, use as often as needed
- A profile stores **both** ML weights (MinIO) **and** an LR parameter template (DB)
- Photos are identified by `lr_catalog_uuid` — LR is the source of truth for IDs
- Writing back = LR develop settings as JSON, never RAW manipulation

---

## Data flow (big picture)

```
┌─────────────┐    Preview+Meta    ┌────────┐    HTTP POST    ┌─────┐
│  LR Plugin  │ ─────────────────▶ │ Bridge │ ─────────────▶ │ API │
│   (Lua)     │                    │(Tauri) │                 │     │
│             │ ◀───────────────── │        │ ◀───────────── │     │
└─────────────┘   Develop Settings └────────┘   Job Status   └──┬──┘
                                                                  │
                    ┌─────────────────────────────────────────────┘
                    │
         ┌──────────▼──────────────────────────────────────────────┐
         │                   Redis Queues                           │
         │  tarsier:jobs:feature  →  tarsier:jobs:inference              │
         │  tarsier:jobs:train                                         │
         └──────┬──────────────────────────┬────────────────────────┘
                │                          │
     ┌──────────▼──────────┐   ┌───────────▼────────────────────────┐
     │   Feature Worker    │   │         Train Worker               │
     │                     │   │                                    │
     │ 1. Load preview     │   │ 1. Load photo features             │
     │    from MinIO       │   │ 2. Train model                     │
     │ 2. Extract          │   │ 3. Save weights → MinIO            │
     │    features         │   │ 4. Update profile → ready          │
     │ 3. Save             │   └────────────────────────────────────┘
     │    pgvector         │
     │ 4. Forward →        │   ┌────────────────────────────────────┐
     │    inference queue  │   │       Inference Worker             │
     └─────────────────────┘   │                                    │
                                │ 1. Load profile + weights         │
                                │ 2. Load feature vector            │
                                │ 3. Compute LR settings            │
                                │ 4. Save result → DB/MinIO         │
                                │ 5. Job → completed                 │
                                └────────────────────────────────────┘
```

---

## Phase 1 — Domain Foundation

**Goal:** Complete DB schema, domain models, updated contracts. No worker code, no ML. But real tables, real migrations, real schemas.

### 1.1 Domain library (`libs/domain`)

- `Photo`, `FeatureVector`, `Profile` as Pydantic models / enums
- `ProfileStatus` enum: `draft | training | ready | failed`
- Extend `JobKind` if needed

### 1.2 Persistence (`libs/persistence`)

New SQLAlchemy models:

```python
# models.py additions
class Photo(Base): ...
class FeatureVector(Base): ...
class Profile(Base): ...
```

Extend the `Job` model:
- `profile_id: UUID | None` (FK → profiles)
- `started_at: datetime | None` (for stuck-job detection, Phase 4)

New repositories:
- `PhotoRepository`: create, get_by_lr_uuid, get_by_id
- `ProfileRepository`: create, get_by_id, set_status, set_artifact
- `FeatureVectorRepository`: create, get_by_photo_id

### 1.3 Migrations (`infra/migrations`)

```
002_create_photos.py
003_create_profiles.py
004_create_feature_vectors.py
005_add_profile_id_to_jobs.py
006_add_started_at_to_jobs.py
```

### 1.4 Update contracts (`packages/contracts`)

Update/create JSON schemas:
- `job-train-request-v1.schema.json` — already exists, stays
- `job-edit-request-v1.schema.json` — already exists, stays
- `photo-upload-v1.schema.json` — **new**: what the plugin sends to the backend
- `edit-result-v1.schema.json` — **new**: LR develop settings that are returned

Extend OpenAPI `bridge-api.yaml`:
- `POST /v1/photos` — upload a photo (preview + metadata)
- `GET /v1/profiles` — list of all profiles
- `GET /v1/profiles/{profile_id}` — profile status

### 1.5 API routes (`services/api`)

New endpoints:
- `POST /v1/photos` — accepts multipart (JPEG preview + JSON metadata), uploads to MinIO, creates a `Photo` record, returns `photo_id`
- `GET /v1/profiles` — lists profiles
- `GET /v1/profiles/{profile_id}` — profile details including status

Adjust `POST /v1/jobs/edit`:
- must validate `profile_id` (does the profile exist? is it `ready`?)
- must check `photo_ids` against known photos

**Deliverable:** `docker compose up` → migrations run through → all endpoints reachable → contracts validate in CI.

---

## Phase 2 — End-to-End Pipeline (Stubs)

**Goal:** Real data flow from the Bridge to returning LR settings. Worker logic is still a stub (no real ML computations), but all status transitions, DB writes and queue messages are real.

### 2.1 Feature worker

```
consume tarsier:jobs:feature
→ load preview from MinIO (s3_key from the Photo record)
→ compute stub features (e.g. 64-dimensional zero vector)
→ write FeatureVector to DB (pgvector)
→ update Photo.feature_vector_id
→ forward envelope → tarsier:jobs:inference
```

### 2.2 Train worker

```
consume tarsier:jobs:train
→ load all photo_ids from the payload
→ load their FeatureVectors (if missing: job FAILED with a clear message)
→ stub: "train" a model (save an empty JSON file in MinIO)
→ update Profile: model_artifact_key, status → ready
→ Job → completed
```

### 2.3 Inference worker

```
consume tarsier:jobs:inference
→ load profile_id from envelope.payload
→ load Profile (model_artifact_key)
→ load the photo's FeatureVector
→ stub: return base_preset (or empty settings)
→ save EditResult in DB/MinIO
→ Job → completed, result_key set
```

### 2.4 EditResult

New concept — where does the result end up?

```
EditResult
├── id            UUID
├── job_id        → Job
├── photo_id      → Photo
├── profile_id    → Profile
├── s3_key        String nullable — full settings file in MinIO
├── lr_settings   JSONB — compact develop settings directly in the DB
│                         (for fast retrieval without a MinIO round trip)
└── created_at
```

New endpoint:
- `GET /v1/jobs/{job_id}/result` — returns `lr_settings` when the job is completed

### 2.5 Bridge (Tauri — minimal)

For Phase 2 a minimal Tauri backend is enough:
- Accepts photo data from the LR plugin (local HTTP server on a port)
- Calls `POST /v1/photos`
- Calls `POST /v1/jobs/edit` or `POST /v1/jobs/train`
- Polls `GET /v1/jobs/{job_id}` until completed
- Returns `lr_settings` to the LR plugin

### 2.6 LR plugin (Lua — minimal)

- Export dialog: selected photos as JPEG preview (1200px longest side)
- Sends preview + EXIF + current develop settings to the Bridge
- Waits for the result (simple polling with a progress dialog)
- Applies `lr_settings` with `photo:developSettings`

**Deliverable:** Select a photo in LR → start a train job → start an edit job → LR settings are applied to the photo. Everything with stub values, but the whole data flow works.

---

## Phase 3 — Real ML Pipeline

**Goal:** Real feature extraction, real training, real inference. Stubs are replaced by real algorithms — the DB schema stays unchanged.

### 3.1 Feature extraction (`libs/inference-pipeline`)

MVP features (no deep learning needed):
```
- Color histogram RGB + HSL (32 bins each = 192 values)
- Global stats: brightness, contrast, saturation (mean + stddev)
- Tone curve characteristics (highlights/shadows/midtones ratio)
- Sharpness estimate (Laplacian variance)
```
→ ~200-dimensional vector, fast to compute, no GPU needed

Later as a drop-in: CLIP embedding (512/768 dim) — the `model_version` field in `FeatureVector` makes this cleanly swappable.

### 3.2 Training (`libs/` new package: `lr-model-trainer`)

MVP model: **gradient boosted trees** (XGBoost/LightGBM) per LR parameter
```
Input:  FeatureVector (200 dim)
Output: Dict[lr_param_name → float]
        e.g. {"exposure": 0.3, "contrast": 15, "highlights": -20, ...}
```

One model is trained per profile — stored as Pickle/ONNX in MinIO.

Training data: the `lr_develop_settings` of the training photos are the labels.

### 3.3 Inference

```
FeatureVector  →  load model from MinIO  →  predict LR settings
```

Output directly as `lr_settings` JSONB → no detour.

### 3.4 Quality assurance

- Mean absolute error per LR parameter as the training metric
- Stored in `Profile.training_metrics` (JSONB, new field)
- Visible in the Bridge UI

**Deliverable:** A real learning effect — the system learns from real LR settings and transfers the style to new photos.

---

## Phase 4 — Production Hardening

**Goal:** The system is reliable, not just functional. No lost jobs, no stuck states, no connection leaks.

### 4.1 Reliable queue (at-least-once delivery)

Current problem: `BLPOP` removes immediately — worker crash = job gone.

Solution with Redis `LMOVE`:
```
BLMOVE {queue} {queue}:processing RIGHT LEFT (atomic)
→ process
→ LREM {queue}:processing 1 {payload} (ack)

Recovery task (at worker start + periodically):
→ scan {queue}:processing
→ jobs older than N minutes → back into {queue}
```

### 4.2 Stuck-job recovery

- The worker sets `started_at` when it picks up a job
- Cron job (or worker startup check): jobs with `status=running` and `started_at < now() - 10min` → back to `queued`, `attempt + 1`
- After `max_attempts` (e.g. 3): `failed` with reason "max_attempts_exceeded"

### 4.3 Retry logic

The `attempt` field in the envelope finally gets used:
```python
MAX_ATTEMPTS = 3
if envelope.attempt >= MAX_ATTEMPTS:
    push_dead_letter(...)
    set_status(FAILED, "max_attempts_exceeded")
else:
    # re-enqueue with attempt+1 and exponential backoff
```

### 4.4 Connection management in workers

Currently a new Redis/DB connection is created per job. Fix:
```python
# main() once:
redis_client = redis_from_env()
publisher = RedisQueuePublisher(redis_client)
session_factory = get_session_factory()

# process_one() takes these as parameters
```

### 4.5 Redis persistence

Add to Redis in `docker-compose.yml`:
```yaml
redis:
  command: redis-server --appendonly yes
  volumes:
    - redis_data:/data
```

### 4.6 Extend CI

- Ruff linting as its own CI job
- API endpoint tests (pytest + httpx TestClient)
- Worker unit tests (mock Redis + DB)
- Docker build check

### 4.7 DB trigger for `updated_at`

SQLAlchemy `onupdate` is unreliable with direct SQL. Postgres trigger:
```sql
CREATE TRIGGER set_updated_at
BEFORE UPDATE ON jobs
FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
-- (likewise for photos, profiles)
```

---

## Open decisions (deliberately deferred)

| Topic | Decision needed by | Note |
|-------|----------------------|-------|
| Auth between Bridge ↔ API | Phase 2 | A shared secret is enough for the MVP |
| SSE vs. polling for job status | Phase 2 | Polling interval: 2s, SSE as a Phase 5 feature |
| LR plugin: which LR parameters to learn? | Phase 3 | Define an initial list, in `lr_output_keys` |
| Model format: Pickle vs. ONNX | Phase 3 | ONNX preferred (more portable) |
| Multi-user / auth | Post-MVP | Currently: single user, no auth |

---

## Milestones

```
Phase 1  ──▶  All tables exist, contracts up to date, API has photo/profile endpoints
Phase 2  ──▶  Photo in LR → LR settings back (stub values, real data flow)
Phase 3  ──▶  Real learning effect demonstrable (MAE < baseline)
Phase 4  ──▶  No job loss under a simulated worker crash
```

---

## What we deliberately do NOT build in the MVP

- Multi-user / accounts
- Web UI (the Bridge desktop app is enough)
- Batch optimizations (many photos in parallel)
- Model versioning with A/B testing
- Cloud deployment / Kubernetes
- Deep learning features (CLIP etc.) — comes as a drop-in after Phase 3
