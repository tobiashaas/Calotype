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
- [x] Bridge: parallel uploads (8 at a time); Canon CR2 verified (179 files), DCT-scaled decoding for full-size-only JPEGs
- [ ] Bridge: test corpus for NEF/ARW/RAF/DNG (Canon CR2/CR3 verified so far)
- [ ] API: update `lr_develop_settings` when an already uploaded photo is registered again (retraining after edits)
- [x] LR Plugin `apps/lr-plugin/LRFrameFlow.lrplugin`: menu items Train / Apply / Bridge status
- [x] LR Plugin: send file path + `getDevelopSettings()` + catalog UUID + EXIF to bridge
- [x] LR Plugin: poll job status (progress + cancel) and apply `lr_settings` in one catalog transaction
- [x] LR Plugin tests with faked SDK modules (`luajit apps/lr-plugin/tests/run.lua`, CI job `lr-plugin`)
- [x] First real Lightroom run (2026-11-07): plugin loads, Bridge status ok, apply on 45 R6 photos ok; fixed os.getenv missing in the sandbox
- [ ] Rest of the Lightroom smoke test: train from Lightroom (`run.py --train N`), `getDevelopSettings()` keys for JPEG/TIFF (`IncrementalTemperature`?)
- [x] End-to-end smoke test: LR → Plugin → Bridge → API → Workers → back to LR — automated (`tools/lr_e2e/run.py`): apply on 5 RAW, sliders = prediction, `WhiteBalance` Custom, restore; all passed 2026-11-07

### Phase 5b — Folder mode & first measurement (done 2026-11-06)
- [x] `xmp.rs`: read `crs:` settings as training targets; write new sidecars / update existing ones (keeps ratings, keywords)
- [x] `lrff-folder train/apply/profiles` (RAW + XMP, no Lightroom), content-based photo ids
- [x] `tools/lrff_eval/synthetic.py`: known-rule test on 60 real CR3 (45 train / 15 test): exposure MAE 0.01 EV, temperature 25 K, 93 % of photos with every slider within tolerance
- [x] Fixed on the real stack: workers crashed on empty queues (redis-py 8 socket timeout ≤ BLPOP) and on any Redis hiccup; `localhost` cost 21 s per connection on Windows → 127.0.0.1 defaults; MinIO image gone → RustFS
- [ ] `lrff-eval` on real edits: hold-out split of the user's own edited photos (needs ~30+ edited RAWs)

### Phase 6 — Culling (planned)
See `docs/adr/005-culling-architecture.md`.
- [x] Plugin: read star ratings, pick/reject flags, color labels (`lr_metadata`); folder mode reads `xmp:Rating`/`xmp:Label`; API refreshes settings + decisions on re-upload (migration 008)
- [x] `THIRD_PARTY_MODELS.md` + model registry with SHA-256 download (`libs/culling/models.py`)
- [x] `libs/culling` prototype: sharpness (subject/face), exposure (face clipping), YuNet faces, MediaPipe blendshapes (eyes closed, smile), dHash series, explainable baseline — 130 ms/photo on 60 real CR3
- [x] Learned scorer (`libs/culling/learned.py`): ROC-AUC 0.74 vs. 0.42 for hand weights against another tool's cull
- [ ] Learned scorer from the user's own ratings (needs rated photos from Lightroom)
- [ ] Swappable model interface via config (`face_detector: yunet | …`)
- [ ] Content/moment features: image embeddings (DINOv2/CLIP), interaction (hug, kiss, eye contact), candid vs. posed
- [ ] Series via embeddings + capture time instead of dHash
- [ ] Eyes "closed" vs. "looking down": separate via gaze/head pitch (blendshapes `eyeLookDown*`)
- [ ] Culling job type: worker (or Bridge-local) + results back to Lightroom as flags/stars/labels
- [ ] Scorer trained on the user's own decisions; explanations per photo; "uncertain" bucket
- [ ] Labeling UI + `lrff-eval cull` (agreement, rescued technically-weak keepers)

### Model v2 (done 2026-11-07)
- [x] Benchmark on 1,837 real edited RAWs (another tool's output, internal measurement only): v1 Ridge 14 % all-sliders-within-tolerance
- [x] Model lab (offline): boosting + tone/color stats + face brightness → 34 %
- [x] Pipeline: versioned features (`histogram-v1`, `histstats-face-v2`), migration 009, `gbr_v2` artifacts with feature version, inference uses the artifact's version → end-to-end 32 %, exposure MAE 0.33 → 0.20 EV
- [x] Style layer: `base_preset` look on top of predictions; `lrff-folder train --style preset.xmp`; XMP tone curves
- [x] Learned culling scorer: ROC-AUC 0.42 (hand weights) → 0.74 vs. another tool's cull
- [x] Tried: DINOv2-small embeddings (PCA 16–64) on top of v2 → all-3 34 % → 37 %, temperature 166 → 150 K, exposure unchanged; not worth torch (~1 GB) + 170 ms/photo yet (`tools/lrff_eval/embed_lab.py`)
- [x] Tried: retrieval (sliders of the most similar edited photos, RefRetouch/Adaptive-Color-Grading idea): alone 14–22 % vs. 34 % for v2, blending/stacking no gain on this (very consistent, tool-generated) benchmark → repeat on a real photographer's edits (`tools/lrff_eval/retrieval_lab.py`)
- [x] Model research 2026-11 (licenses checked at the source): keep YuNet + MediaPipe; DINOv3 has a custom Meta license (plug-in only); avoid pyiqa (PolyForm Noncommercial) and its weights (CC BY-NC-SA), Q-Align, QualiCLIP (non-commercial), LAION Aesthetic V2.5 (AGPL), MobileCLIP weights (research-only)
- [x] Benchmarked embeddings (all Apache-2.0): DINOv2-S, Perception Encoder S16/B16, SigLIP 2 B16 → editing 33–37 % vs. 34 % without, culling AUC 0.72–0.73 vs. 0.74 without, +230–380 ms/photo on CPU → none integrated for now (`tools/lrff_eval/embed_compare.py`)
- [ ] Zero-shot text prompts on SigLIP 2 / Perception Encoder ("blurry photo", "people hugging", "candid moment") as culling features — untested
- [ ] Next model step for exposure: EXIF context (ISO, shutter, aperture → scene EV; folder mode must send EXIF) and consistency within a series/shoot (relative to neighbours)
- [ ] Predict RAW white balance relative to as-shot (needs EXIF as-shot from the RAW)

### Straighten & people (done 2026-11-08)
- [x] Straighten from the photo's own lines (keystone-aware), Lightroom crop keys verified in Lightroom, option in edit requests / plugin (DE/EN) / `lrff-folder apply --straighten`; own crops stay
- [x] Server under load: long jobs were re-run by the reaper and returned results 2–3×; progress heartbeat, one reaper per job kind, upserted edit results (migration 010)
- [x] Culling measured against the photographer's real choice (exports in the catalog), leave-one-group-out (`tools/lrff_eval/cull_groups.py`)
- [x] Group photos by person (SFace, Apache-2.0); ranking within each person gave no gain on kindergarten shoots
- [ ] Subject mask ("person pops") in the style layer: write the mask definition (Lightroom computes the mask itself — `.acr` sidecars); test via plugin and XMP together with the user
- [ ] Straighten: let the user judge the contact sheets; learn from the user's own corrections once there are some
- [ ] Culling within a person's photos: better moment/expression cues (see embedding result in the culling notes)

### Backlog / Nice-to-have
- [ ] **Better model (biggest quality lever):** CNN on the image (e.g. pretrained ResNet/EfficientNet backbone, one head per slider group) instead of 128-dim histogram + Ridge; export to ONNX for optional local inference in the Bridge
- [ ] Predict RAW white balance relative to as-shot instead of absolute Kelvin
- [ ] More sliders: Texture, Clarity, Dehaze, tone curve, HSL, crop/straighten
- [ ] XMP sidecar writer (crs:) as second output path besides `applyDevelopSettings`
- [ ] Add a `GET /v1/jobs` list endpoint with pagination and status filter
- [ ] Profile versioning: bump `version` on retrain instead of overwriting artifact
- [ ] S3 presigned URLs for returning edit result images (not just `lr_settings`)
- [ ] Admin endpoint to manually set Profile status (e.g. force `ready` for testing)
