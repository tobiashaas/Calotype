# LRFrameFlow — TODO

This file tracks completed milestones and open work items.
Update it whenever a phase is finished or new tasks are identified.

---

## Completed

### Phase 1 — Domain Foundation
- [x] `ProfileStatus` enum (`draft | training | ready | failed`)
- [x] DB models: `Photo`, `Profile`, `FeatureVector` (pgvector 128-dim), `EditResult`
- [x] Extended `Job` model with `profile_id` FK and `started_at`
- [x] Repositories: `PhotoRepository`, `ProfileRepository`, `FeatureVectorRepository`, `EditResultRepository`
- [x] Migrations 002–006 (photos, profiles, feature_vectors, edit_results, extend jobs)
- [x] API endpoints: `POST /v1/photos`, `GET /v1/profiles`, `GET /v1/profiles/{id}`, `GET /v1/jobs/{id}/result`
- [x] `POST /v1/jobs/edit` now validates profile status (must be `ready`) and photo_ids
- [x] `POST /v1/jobs/train` creates a `Profile` in `DRAFT` status
- [x] OpenAPI spec updated with all new endpoints and schemas
- [x] `photo-upload-v1.schema.json` contract added

### Phase 2 — Real Data Flow (with stubs)
- [x] Feature worker: downloads JPEG from MinIO, skips if vector exists, forwards to inference queue
- [x] Train worker: loads feature vectors + LR settings, saves stub model JSON to MinIO, sets Profile → READY
- [x] Inference worker: loads model artifact from MinIO, creates `EditResult` per photo, sets Job → COMPLETED
- [x] All workers: connection anti-pattern fixed (redis/DB created once in `main()`)
- [x] API: `boto3` + `python-multipart` deps, `storage.py` helper, `get_storage()` dep
- [x] `.env` with port overrides (Postgres 5433, MinIO 9100/9101)

### Phase 3 — Real ML Pipeline
- [x] `extract_features()`: Pillow-based 128-dim histogram (R/G/B/Brightness, 32 bins each)
- [x] `train_model()`: scikit-learn `MultiOutputRegressor(Ridge)` + `StandardScaler`, joblib bytes
- [x] `run_inference()`: deserialize joblib model, predict 10 LR params, zero-model fallback < 3 samples
- [x] Migration 007: vector dim 200 → 128
- [x] All workers use real pipeline functions; inference-pipeline dep added to feature + train workers

---

## Open

### Phase 4 — Production Hardening
- [x] **Redis AOF persistence**: `appendonly yes --appendfsync everysec` in compose + `redis_data` volume
- [x] **Stuck job recovery**: `libs/persistence/src/lr_frameflow_persistence/reaper.py` — resets `running` jobs after 10 min timeout, re-enqueues on the correct queue; runs at startup + every 60s in daemon thread in all 3 workers
- [x] **At-least-once delivery**: `set_status(RUNNING)` now sets `started_at`; reaper uses `enqueue_to(queue_name)` to push back on the exact worker queue; feature_worker `forward_to_inference` is idempotent (FeatureVectors skipped if already exist)
- [x] **Worker health checks**: `libs/observability/src/lr_frameflow_observability/heartbeat.py` — writes Unix timestamp file every 15s; all 3 workers start heartbeat thread; docker-compose has HEALTHCHECK comment template
- [x] **CI linting**: Ruff check step added to CI for all Python source dirs
- [x] **CI tests**: API integration tests (14 tests, mock-based, no Postgres) in `services/api/tests/`; added `api-tests` job to CI
- [x] **Contracts validation**: extended `validate_contracts.py` with edit-request + photo-upload schemas + examples; JSON parse check for all schema files
- [x] **Observability**: `libs/observability` — `JsonFormatter`, `RequestIdFilter`, `configure_logging()`, `request_id` contextvar; FastAPI `RequestIdMiddleware` sets/propagates `X-Request-ID`; all workers call `configure_logging()` + `set_request_id()` from envelope `trace_context`; env `LOG_FORMAT=text` falls back to plain text
- [x] **Rate limiting / backpressure**: `RateLimitMiddleware` (fixed-window, Redis-backed, per-IP, 60 req/60s on `/v1/jobs/*`); `QueueFullError` when `LLEN > MAX_QUEUE_DEPTH` (default 500) → 429; env vars `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`, `MAX_QUEUE_DEPTH`

### Phase 5 — Bridge & Plugin Integration
Architecture: see `docs/adr/004-bridge-localhost-architecture.md`.

Prerequisites (done 2026-11-06):
- [x] Train worker computes missing feature vectors itself (fresh uploads used to fail with "no feature vectors")
- [x] `libs/edit-serializer`: internal params ↔ LR develop settings (names, ranges, RAW vs JPEG white balance), used by train + inference worker
- [x] No silent zeros: undecodable previews are skipped, missing/broken model artifact fails the job, < 3 usable training photos fails the profile
- [x] ADR 004: Bridge as localhost service, plugin as UI, unedited image as model input

Open:
- [x] Rust toolchain + Tauri 2 app in `apps/bridge` (workspace: `core/` + `src-tauri/` + `ui/`)
- [x] Contract `packages/contracts/openapi/plugin-bridge-api.yaml` (plugin ↔ bridge, validated in CI)
- [x] Bridge: axum server on 127.0.0.1:47600 + token in `bridge.json` (`X-LRFF-Token`)
- [x] Bridge: SQLite outbox with retry/backoff for photos + train/edit jobs; stable Idempotency-Key; status polling; edit results mapped back to catalog UUIDs
- [x] Bridge: preview from original file (largest embedded RAW JPEG / JPEG/TIFF original, longest side ≤ 1200 px); unreachable file = retry, broken file = failed
- [x] Bridge: status window (server reachable, queue counts, server address, "Retry now"); headless binary `lrff-bridge-headless`
- [x] CI job `bridge-core` (fmt, clippy, tests)
- [ ] Bridge: tray mode (closing the window must not stop the bridge) + autostart
- [x] Bridge: orientation from RAW container (TIFF IFD0 / CR3 `CMT1`) or JPEG EXIF; verified on 30 real Canon CR3 (portrait + landscape)
- [x] Bridge: pick smallest embedded JPEG covering 1200 px instead of full-size → ~200 ms/photo (release) instead of 2–5 s
- [x] API + Bridge: `profile_id` and short `failure_reason` in job status (workers store a one-line reason, traceback stays in the log)
- [ ] Bridge: test corpus for NEF/ARW/RAF/DNG (only CR3 verified so far); parallel preview building for big shoots
- [ ] API: update `lr_develop_settings` when an already uploaded photo is registered again (retraining after edits)
- [x] LR Plugin `apps/lr-plugin/LRFrameFlow.lrplugin`: menu items Train / Apply / Bridge status
- [x] LR Plugin: send file path + `getDevelopSettings()` + catalog UUID + EXIF to bridge
- [x] LR Plugin: poll job status (progress + cancel) and apply `lr_settings` in one catalog transaction
- [x] LR Plugin tests with faked SDK modules (`luajit apps/lr-plugin/tests/run.lua`, CI job `lr-plugin`)
- [ ] Smoke test in real Lightroom: install plugin, `getDevelopSettings()` keys for JPEG/TIFF (`IncrementalTemperature`?), `applyDevelopSettings` with `WhiteBalance = "Custom"`, `appData` path
- [ ] End-to-end smoke test: LR → Plugin → Bridge → API → Workers → back to LR

### Phase 5b — Folder mode & first measurement (done 2026-11-06)
- [x] `xmp.rs`: read `crs:` settings as training targets; write new sidecars / update existing ones (keeps ratings, keywords)
- [x] `lrff-folder train/apply/profiles` (RAW + XMP, no Lightroom), content-based photo ids
- [x] `tools/lrff_eval/synthetic.py`: known-rule test on 60 real CR3 (45 train / 15 test): exposure MAE 0.01 EV, temperature 25 K, 93 % of photos with every slider within tolerance
- [x] Fixed on the real stack: workers crashed on empty queues (redis-py 8 socket timeout ≤ BLPOP) and on any Redis hiccup; `localhost` cost 21 s per connection on Windows → 127.0.0.1 defaults; MinIO image gone → RustFS
- [ ] `lrff-eval` on real edits: hold-out split of the user's own edited photos (needs ~30+ edited RAWs)

### Phase 6 — Culling (planned)
See `docs/adr/005-culling-architecture.md`.
- [ ] Plugin: read star ratings, pick/reject flags, color labels as culling labels
- [ ] Swappable model interface (`face_detector: …`), `THIRD_PARTY_MODELS.md`
- [ ] Feature extractors (technical, face, emotion/moment, content, series) with permissive models
- [ ] Scorer trained on the user's own decisions; explanations per photo; "uncertain" bucket
- [ ] Labeling UI + `lrff-eval cull` (agreement, rescued technically-weak keepers)

### Backlog / Nice-to-have
- [ ] **Better model (biggest quality lever):** CNN on the image (e.g. pretrained ResNet/EfficientNet backbone, one head per slider group) instead of 128-dim histogram + Ridge; export to ONNX for optional local inference in the Bridge
- [ ] Predict RAW white balance relative to as-shot instead of absolute Kelvin
- [ ] More sliders: Texture, Clarity, Dehaze, tone curve, HSL, crop/straighten
- [ ] XMP sidecar writer (crs:) as second output path besides `applyDevelopSettings`
- [ ] Add a `GET /v1/jobs` list endpoint with pagination and status filter
- [ ] Profile versioning: bump `version` on retrain instead of overwriting artifact
- [ ] S3 presigned URLs for returning edit result images (not just `lr_settings`)
- [ ] Admin endpoint to manually set Profile status (e.g. force `ready` for testing)
