# Calotype — TODO

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
- [x] **Stuck job recovery**: `libs/persistence/src/calotype_persistence/reaper.py` — resets `running` jobs after 10 min timeout, re-enqueues on the correct queue; runs at startup + every 60s in daemon thread in all 3 workers
- [x] **At-least-once delivery**: `set_status(RUNNING)` now sets `started_at`; reaper uses `enqueue_to(queue_name)` to push back on the exact worker queue; feature_worker `forward_to_inference` is idempotent (FeatureVectors skipped if already exist)
- [x] **Worker health checks**: `libs/observability/src/calotype_observability/heartbeat.py` — writes Unix timestamp file every 15s; all 3 workers start heartbeat thread; docker-compose has HEALTHCHECK comment template
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
- [x] Bridge: axum server on 127.0.0.1:47600 + token in `bridge.json` (`X-Calotype-Token`)
- [x] Bridge: SQLite outbox with retry/backoff for photos + train/edit jobs; stable Idempotency-Key; status polling; edit results mapped back to catalog UUIDs
- [x] Bridge: preview from original file (largest embedded RAW JPEG / JPEG/TIFF original, longest side ≤ 1200 px); unreachable file = retry, broken file = failed
- [x] Bridge: status window (server reachable, queue counts, server address, "Retry now"); headless binary `calotype-bridge-headless`
- [x] CI job `bridge-core` (fmt, clippy, tests)
- [ ] Bridge: tray mode (closing the window must not stop the bridge) + autostart
- [x] Bridge: orientation from RAW container (TIFF IFD0 / CR3 `CMT1`) or JPEG EXIF; verified on 30 real Canon CR3 (portrait + landscape)
- [x] Bridge: pick smallest embedded JPEG covering 1200 px instead of full-size → ~200 ms/photo (release) instead of 2–5 s
- [x] API + Bridge: `profile_id` and short `failure_reason` in job status (workers store a one-line reason, traceback stays in the log)
- [x] Bridge: parallel uploads (8 at a time); Canon CR2 verified (179 files), DCT-scaled decoding for full-size-only JPEGs
- [ ] Bridge: test corpus for NEF/ARW/RAF/DNG (Canon CR2/CR3 verified so far)
- [ ] API: update `lr_develop_settings` when an already uploaded photo is registered again (retraining after edits)
- [x] LR Plugin `apps/lr-plugin/Calotype.lrplugin`: menu items Train / Apply / Bridge status
- [x] LR Plugin: send file path + `getDevelopSettings()` + catalog UUID + EXIF to bridge
- [x] LR Plugin: poll job status (progress + cancel) and apply `lr_settings` in one catalog transaction
- [x] LR Plugin tests with faked SDK modules (`luajit apps/lr-plugin/tests/run.lua`, CI job `lr-plugin`)
- [x] First real Lightroom run (2026-11-07): plugin loads, Bridge status ok, apply on 45 R6 photos ok; fixed os.getenv missing in the sandbox
- [x] Train from Lightroom through the automation channel (`run.py --train 20`, 2026-11-08)
- [ ] Lightroom smoke test for JPEG/TIFF: `getDevelopSettings()` keys (`IncrementalTemperature`?)
- [x] End-to-end smoke test: LR → Plugin → Bridge → API → Workers → back to LR — automated (`tools/lr_e2e/run.py`): apply on 5 RAW, sliders = prediction, `WhiteBalance` Custom, restore; all passed 2026-11-07

### Phase 5b — Folder mode & first measurement (done 2026-11-06)
- [x] `xmp.rs`: read `crs:` settings as training targets; write new sidecars / update existing ones (keeps ratings, keywords)
- [x] `calotype-folder train/apply/profiles` (RAW + XMP, no Lightroom), content-based photo ids
- [x] `tools/eval/synthetic.py`: known-rule test on 60 real CR3 (45 train / 15 test): exposure MAE 0.01 EV, temperature 25 K, 93 % of photos with every slider within tolerance
- [x] Fixed on the real stack: workers crashed on empty queues (redis-py 8 socket timeout ≤ BLPOP) and on any Redis hiccup; `localhost` cost 21 s per connection on Windows → 127.0.0.1 defaults; MinIO image gone → RustFS
- [ ] `calotype-eval` on real edits: hold-out split of the user's own edited photos (needs ~30+ edited RAWs)

### Phase 6 — Culling (first version done 2026-11-08)
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
- [x] Culling job type (2026-11-08): `cull_worker`, `POST /v1/jobs/cull`, Bridge `bridge-cull-v1`, plugin menu → collections Calotype > Culling <date> > Keep / Check / Sort out (non-destructive); learns from the stars/flags among the selection; verified in Lightroom (`tools/lr_e2e/cull_check.py`)
- [x] Plugin read stars, flags and EXIF inside a plain `pcall` — it cannot yield in Lightroom, so they always arrived empty; fixed with `LrTasks.pcall` + regression test
- [ ] **Culling profiles from earlier shoots** (next step): learning only from ratings inside the culled selection helps little (kindergarten exports, ROC-AUC: rules 0.53, 10+10 rated 0.56, 40+40 0.60), learning from other shoots' decisions gives 0.65. Plan: cull request gets optional `reference_photo_ids` (or a trained culling profile like edit profiles); plugin option "also learn from my earlier ratings". Decide the UX with the user (which photos, how many, upload time)
- [x] Folder mode `calotype-folder cull <dir> [--out]`: color label green / yellow / red + `calotype:Cull`/`calotype:CullReason` in the sidecar, stars and edits untouched; sidecars with stars/labels teach the scorer (2026-11-08, 155 wedding RAWs learned, 150 without sidecars by rules)
- [ ] Culling: show the reason per photo in Lightroom (plugin metadata field) and a "why" view
- [ ] Scorer trained on the user's own decisions; explanations per photo; "uncertain" bucket
- [ ] Labeling UI + `calotype-eval cull` (agreement, rescued technically-weak keepers)

### Model v2 (done 2026-11-07)
- [x] Benchmark on 1,837 real edited RAWs (another tool's output, internal measurement only): v1 Ridge 14 % all-sliders-within-tolerance
- [x] Model lab (offline): boosting + tone/color stats + face brightness → 34 %
- [x] Pipeline: versioned features (`histogram-v1`, `histstats-face-v2`), migration 009, `gbr_v2` artifacts with feature version, inference uses the artifact's version → end-to-end 32 %, exposure MAE 0.33 → 0.20 EV
- [x] Style layer: `base_preset` look on top of predictions; `calotype-folder train --style preset.xmp`; XMP tone curves
- [x] Learned culling scorer: ROC-AUC 0.42 (hand weights) → 0.74 vs. another tool's cull
- [x] Tried: DINOv2-small embeddings (PCA 16–64) on top of v2 → all-3 34 % → 37 %, temperature 166 → 150 K, exposure unchanged; not worth torch (~1 GB) + 170 ms/photo yet (`tools/eval/embed_lab.py`)
- [x] Tried: retrieval (sliders of the most similar edited photos, RefRetouch/Adaptive-Color-Grading idea): alone 14–22 % vs. 34 % for v2, blending/stacking no gain on this (very consistent, tool-generated) benchmark → repeat on a real photographer's edits (`tools/eval/retrieval_lab.py`)
- [x] Model research 2026-11 (licenses checked at the source): keep YuNet + MediaPipe; DINOv3 has a custom Meta license (plug-in only); avoid pyiqa (PolyForm Noncommercial) and its weights (CC BY-NC-SA), Q-Align, QualiCLIP (non-commercial), LAION Aesthetic V2.5 (AGPL), MobileCLIP weights (research-only)
- [x] Benchmarked embeddings (all Apache-2.0): DINOv2-S, Perception Encoder S16/B16, SigLIP 2 B16 → editing 33–37 % vs. 34 % without, culling AUC 0.72–0.73 vs. 0.74 without, +230–380 ms/photo on CPU → none integrated for now (`tools/eval/embed_compare.py`)
- [ ] Zero-shot text prompts on SigLIP 2 / Perception Encoder ("blurry photo", "people hugging", "candid moment") as culling features — untested
- [ ] Next model step for exposure: EXIF context (ISO, shutter, aperture → scene EV; folder mode must send EXIF) and consistency within a series/shoot (relative to neighbours)
- [ ] Predict RAW white balance relative to as-shot (needs EXIF as-shot from the RAW). Why it matters (2026-11-08): a profile trained on one shoot/camera (R6) applied to another (5D, same look) gets exposure MAE 0.28 EV (guessing 0.64) but temperature only 21–26 % within ±150 K — absolute Kelvin carries the camera. Not possible via the SDK: `applyDevelopSettings{WhiteBalance="As Shot"}` keeps the old Temperature value (Lightroom recomputes only when rendering). Needs as-shot multipliers from the RAW + a per-camera mapping to Lightroom's Kelvin (LibRaw is LGPL — prefer an own parser in the Bridge)
- [ ] Benchmarks: report contiguous-block / other-shoot splits, not only random splits — random splits put near-identical neighbours into training (R6: all-6 within 34 % random vs. 9 % by blocks). Stronger regularization (shallow boosting, Ridge α 10–100) does not help across shoots (exposure ~30 % either way) — the gap is in the data, not the model

### Straighten & people (done 2026-11-08)
- [x] Straighten from the photo's own lines (keystone-aware), Lightroom crop keys verified in Lightroom, option in edit requests / plugin (DE/EN) / `calotype-folder apply --straighten`; own crops stay
- [x] Server under load: long jobs were re-run by the reaper and returned results 2–3×; progress heartbeat, one reaper per job kind, upserted edit results (migration 010)
- [x] Culling measured against the photographer's real choice (exports in the catalog), leave-one-group-out (`tools/eval/cull_groups.py`)
- [x] Group photos by person (SFace, Apache-2.0); ranking within each person gave no gain on kindergarten shoots
- [x] Retouch with Lightroom AI masks (2026-11-08): own presets (subject, background, skin, eyes, teeth, sky) installed by the Bridge, applied with `applyDevelopPreset`, detected with `photo:updateAISettings`, empty masks removed, own masks kept, snapshot "Calotype: before"; verified in Lightroom (`retouch_check.py`). Approach from Retoucan (MIT). Removing and adding masks must not share one transaction
- [ ] Retouch: learn the local mask values from the photographer's own masks in the training photos (per profile); strength per photo
- [ ] (old note) Subject mask ("person pops") in the style layer: write only the mask definition, Lightroom computes the mask itself (`.acr` sidecars; another tool writes the same `MaskDigest` into every photo, so the digest is not checked). Found 2026-11-08: `photo:applyDevelopSettings` with `MaskGroupBasedCorrections` never returns (plugin task hangs, nothing written) → test (a) XMP sidecar + "Read metadata from file" and (b) a plugin develop preset with the mask, together with the user
- [ ] Straighten: let the user judge the contact sheets; learn from the user's own corrections once there are some
- [ ] Culling within a person's photos: better moment/expression cues (see embedding result in the culling notes)

### Looks, rename, speed (done 2026-11-08)
- [x] Eight own looks (CC0, DE/EN names) + six retouch presets generated by `tools/presets/build.py`; the Bridge installs them into Camera Raw's settings folder on start (`install_presets`, default on); a test keeps `presets/` in sync with the generator
- [x] Renamed to **Calotype** (ADR 006, briefly Tarsier): packages, commands, plugin id, data folder, env vars, token header, XMP namespace, queues; old installations migrate (data folder, model cache, preset folders, mask names, `lrff:` attributes)
- [x] Bridge reads only the first 4 MB of a RAW when it holds a mid-size preview: 30/30 previews identical, CR3 from USB 650 → 237 ms per photo, ~85 % less data over a NAS
- [x] Pooled base model from other shoots (offline, `tools/eval`): with 20 own photos R6 white balance 14 → 32 % within tolerance but exposure worse; 5D exposure 14 → 37 % — helps new users, mixed styles can hurt → per-user opt-in, not default
- [ ] Re-run all Lightroom end-to-end tests under the renamed plugin (`Calotype.lrplugin` must be added once in the Plug-in Manager)
- [x] `calotype-folder train` reads several folders, `--recursive` (skips `.lrdata`, `@eaDir`, `._*`) and `--catalogs` (edits straight from old `.lrcat` files, read-only); `--dry-run` counts first
- [x] Hold-out by wedding on the maintainer's archive (2026-11-09; trained on 10,154 photos of 8 weddings, scored on 3 unseen weddings, 3,192 photos, truth from their catalogs): the model alone does not transfer — exposure ±0.15 EV 27 %, temperature ±150 K 21 %, all sliders 1 %. The look (contrast, blacks, saturation …) is synced per wedding and cannot be guessed. **Calibrating on k edited photos of the same wedding** (pred = mean_k(truth) + β·(model − mean_k(model)), β from the k photos) brings the look sliders to 95–100 % with k = 5 (contrast 49 % on one wedding), exposure 40–54 %, all sliders 3–6 % (2019) / 33 % (2015). Temperature stays at 13–20 % on 2019 weddings (white balance varied per scene) → as-shot-relative target
- [x] Business hold-out (2026-11-14; maintainer's client jobs, 4,900 edited photos in 9 catalogs; trained on 2,893 of 4 clients, scored on 2 unseen clients): model alone 0 % all-within; calibration on k photos of the shoot ≈ their plain mean (the global model adds little per photo). **In-shoot learning** — ridge on the photo's features fitted on the k edited photos of the same shoot — helps varied shoots (DVAG, k = 20: all-within 2 → 17 %, temperature 28 → 40 %) and hurts uniform ones (dentist: 57 → 47 %). **Per-slider choice by 5-fold CV on the k photos** (mean vs. in-shoot ridge) is best or near-best on both: dentist k = 20 → 64 %, k = 50 → 76 %; DVAG k = 20 → 13 %, k = 50 → 23 %
- [ ] **Shoot calibration** (next): edit request gets optional `reference_photo_ids` (already edited photos of the same shoot); inference takes their mean per slider and, where 5-fold CV on them says so, adds an in-shoot ridge on the features; the global profile only where the shoot gives nothing. Plugin option "learn from the edited photos in this selection", folder mode `apply --reference <dir>`
- [x] Profile "Business / Aufträge" on 4,900 photos of 6 clients (2026-11-14)
- [x] Final wedding profile "Hochzeit 2015–2019" on 13,338 photos of 11 weddings (2026-11-09); the trained shoots were removed from E: afterwards (originals on the NAS), their catalogs kept locally for the measurements
- [ ] Wedding archive: most 2017/18 shoots have neither XMP nor catalog on E: (disk full during the copy; one truncated CR2) → copy their `.lrcat` files from the NAS
- [ ] License for the code (presets are CC0)

### Backlog / Nice-to-have
- [ ] **Bigger model:** CNN/embedding backbone on the image instead of hand features (tried DINOv2/SigLIP/PE: no gain yet, see Model v2); ONNX for optional local inference in the Bridge
- [ ] More sliders: Texture, Clarity, Dehaze, tone curve, HSL (today only via the profile's fixed look)
- [ ] Ruff upgrade: CI pins 0.8.1; 0.17 reports 49 findings (14 × B008 = FastAPI `Depends`, ignore via config; imports, blind excepts)
- [ ] Other raw converters: RawTherapee / darktable sidecars, Capture One (needs an ADR)
- [ ] Add a `GET /v1/jobs` list endpoint with pagination and status filter
- [ ] Profile versioning: bump `version` on retrain instead of overwriting artifact
- [ ] S3 presigned URLs for returning edit result images (not just `lr_settings`)
- [ ] Admin endpoint to manually set Profile status (e.g. force `ready` for testing)
