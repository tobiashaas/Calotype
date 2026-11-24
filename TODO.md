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
- [x] **Stuck job recovery**: `libs/persistence/src/calotype_persistence/reaper.py` (since ADR 007 `calotype_worker_runtime.reaper`) — resets `running` jobs after 10 min timeout, re-enqueues on the correct queue; runs at startup + every 60s in daemon thread in all 3 workers
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
- [x] Camera exposure settings in shoot calibration (2026-11-21): log2 of ISO, shutter time and f-number plus the exposure compensation join the features for exposure (`shoot.CAMERA_SLIDERS`); the plugin now also sends `exposure_bias`. Two yardstick shoots, exposure within 0.15 EV with 10 / 20 / 50 examples: wedding 33.5 / 39.6 / 46.3 → 35.3 / 41.2 / 46.8 %, kindergarten 49.7 / 57.3 / 67.6 → 55.5 / 61.0 / 70.2 %. Canon's metered EV would add about one more point (not built: maker-specific)
- [ ] The same in folder mode (the Bridge sends only the capture time there) and in profile training
- [ ] Predict RAW white balance relative to as-shot (needs EXIF as-shot from the RAW). Why it matters (2026-11-08): a profile trained on one shoot/camera (R6) applied to another (5D, same look) gets exposure MAE 0.28 EV (guessing 0.64) but temperature only 21–26 % within ±150 K — absolute Kelvin carries the camera. Not possible via the SDK: `applyDevelopSettings{WhiteBalance="As Shot"}` keeps the old Temperature value (Lightroom recomputes only when rendering). Needs as-shot multipliers from the RAW + a per-camera mapping to Lightroom's Kelvin (LibRaw is LGPL — prefer an own parser in the Bridge)
- [ ] Benchmarks: report contiguous-block / other-shoot splits, not only random splits — random splits put near-identical neighbours into training (R6: all-6 within 34 % random vs. 9 % by blocks). Stronger regularization (shallow boosting, Ridge α 10–100) does not help across shoots (exposure ~30 % either way) — the gap is in the data, not the model

### Straighten & people (done 2026-11-08)
- [x] Straighten from the photo's own lines (keystone-aware), Lightroom crop keys verified in Lightroom, option in edit requests / plugin (DE/EN) / `calotype-folder apply --straighten`; own crops stay
- [x] Server under load: long jobs were re-run by the reaper and returned results 2–3×; progress heartbeat, one reaper per job kind, upserted edit results (migration 010)
- [x] Culling measured against the photographer's real choice (exports in the catalog), leave-one-group-out (`tools/eval/cull_groups.py`)
- [x] Group photos by person (SFace, Apache-2.0); ranking within each person gave no gain on kindergarten shoots
- [x] Retouch with Lightroom AI masks (2026-11-08): own presets (subject, background, skin, eyes, teeth, sky) installed by the Bridge, applied with `applyDevelopPreset`, detected with `photo:updateAISettings`, empty masks removed, own masks kept, snapshot "Calotype: before"; verified in Lightroom (`retouch_check.py`). Approach from Retoucan (MIT). Removing and adding masks must not share one transaction
- [x] Retouch: learn the local mask values from the photographer's own masks (2026-11-15): per profile at training, per shoot with `learn_from_edits`; verified in Lightroom (`mask_strength_check.py`)
- [x] Look from the photographer's own Lightroom presets (2026-11-16): "Look" popup in train and apply, `base_preset` in the edit request replaces the profile's
- [ ] Learned mask strengths in folder mode: the XMP reader and the catalog reader drop nested masks
- [ ] (old note) Subject mask ("person pops") in the style layer: write only the mask definition, Lightroom computes the mask itself (`.acr` sidecars; another tool writes the same `MaskDigest` into every photo, so the digest is not checked). Found 2026-11-08: `photo:applyDevelopSettings` with `MaskGroupBasedCorrections` never returns (plugin task hangs, nothing written) → test (a) XMP sidecar + "Read metadata from file" and (b) a plugin develop preset with the mask, together with the user
- [ ] Straighten: let the user judge the contact sheets; learn from the user's own corrections once there are some
- [ ] Culling within a person's photos: better moment/expression cues (see embedding result in the culling notes)

### Looks, rename, speed (done 2026-11-08)
- [x] Eight own looks (CC0, DE/EN names) + six retouch presets generated by `tools/presets/build.py`; the Bridge installs them into Camera Raw's settings folder on start (`install_presets`, default on); a test keeps `presets/` in sync with the generator
- [x] Renamed to **Calotype** (ADR 006, briefly Tarsier): packages, commands, plugin id, data folder, env vars, token header, XMP namespace, queues; old installations migrate (data folder, model cache, preset folders, mask names, `lrff:` attributes)
- [x] Bridge reads only the first 4 MB of a RAW when it holds a mid-size preview: 30/30 previews identical, CR3 from USB 650 → 237 ms per photo, ~85 % less data over a NAS
- [x] Pooled base model from other shoots (offline, `tools/eval`): with 20 own photos R6 white balance 14 → 32 % within tolerance but exposure worse; 5D exposure 14 → 37 % — helps new users, mixed styles can hurt → per-user opt-in, not default
- [x] One definition of the retouch kinds (2026-11-24): `RETOUCH` in `tools/presets/build.py` writes the presets, the manifest `presets/retouch/retouch.json`, edit-serializer's `retouch_kinds.py`, the plugin's `RetouchKinds.lua` and German titles; the sync test catches drift. Adding a kind = one entry + run the script (`presets/README.md`)
- [ ] Re-run all Lightroom end-to-end tests under the renamed plugin (`Calotype.lrplugin` must be added once in the Plug-in Manager)
- [x] `calotype-folder train` reads several folders, `--recursive` (skips `.lrdata`, `@eaDir`, `._*`) and `--catalogs` (edits straight from old `.lrcat` files, read-only); `--dry-run` counts first
- [x] Hold-out by wedding on the maintainer's archive (2026-11-09; trained on 10,154 photos of 8 weddings, scored on 3 unseen weddings, 3,192 photos, truth from their catalogs): the model alone does not transfer — exposure ±0.15 EV 27 %, temperature ±150 K 21 %, all sliders 1 %. The look (contrast, blacks, saturation …) is synced per wedding and cannot be guessed. **Calibrating on k edited photos of the same wedding** (pred = mean_k(truth) + β·(model − mean_k(model)), β from the k photos) brings the look sliders to 95–100 % with k = 5 (contrast 49 % on one wedding), exposure 40–54 %, all sliders 3–6 % (2019) / 33 % (2015). Temperature stays at 13–20 % on 2019 weddings (white balance varied per scene) → as-shot-relative target
- [x] Business hold-out (2026-11-14; maintainer's client jobs, trained on 4 clients, scored on 2 unseen clients): model alone 0 % all-within. Learning from k edited photos of the same shoot, per slider chosen by 5-fold CV on them (their mean, mean + β·model, or an in-shoot ridge on the photo's features): client job A (475 photos, one look) k = 20 → 12 % all-within, k = 50 → 22 %; temperature 0 → 37 / 46 %, contrast 45 → 91 %. Dentist (135 photos, every photo edited on its own) stays at ~1 % all-within, exposure 7 → 52 %. **Correction:** the first measurement reported 64 / 76 % for the dentist — Lightroom logs every export as a history step, so 1,129 photos that were only imported and exported counted as edited (now fixed in `catalog.rs`, see below)
- [x] **Shoot calibration** (2026-11-14): edit request `learn_from_edits` — photos of the selection the photographer already edited (their sliders differ from the selection's untouched state: Lightroom defaults, else the most common state = import preset; as-shot Kelvin ignored) set the shoot's look and stay as they are; the others are predicted by `calotype_inference_pipeline.shoot.calibrate`. Plugin option in the apply dialog (default off), automation arg `learn_from_edits`, folder mode `apply --learn-from-edits` (sidecars written by Calotype are no examples). End to end on 60 client job A photos (20 edited, profile from other clients): all sliders 0/40 → 7/40, temperature 0 → 45 %, contrast 42 → 80 %, highlights 8 → 75 %
- [x] Catalog reader: export steps ("Exportieren - PicDrop FTP Upload …") are not edits — 16,540 of 26,000 last history steps in the archive were exports; 1,726 client-job photos had been trained on as "edited" with untouched settings. Weddings unaffected
- [x] **Series** (2026-11-14): with capture times the closest edited photo in time is a fourth candidate per slider (same scene, same light). Client jobs, all sliders within tolerance, k = 20 edited: client job A 13 → 28 % (k = 50: 20 → 45 %), barber 0 → 41 %, team day 12 → 27 %, never worse. Times from Lightroom's `dateTimeOriginalISO8601` (plugin) or the RAW's IFD0 `DateTime` (folder mode, CR2/CR3/NEF/ARW/DNG)
- [ ] **White balance relative to as-shot** — measured 2026-11-14 on client jobs: as-shot Kelvin (Canon `ColorTempAsShot`) as a calibration candidate lifts temperature where the photographer follows the camera (k = 20: 76 → 86 %, 32 → 56 %, 12 → 27 %) and is never chosen where they set a fixed white balance. Missing: the value in the product — Lightroom does not expose as-shot for edited photos; Canon keeps it in camera-specific MakerNotes (`ColorData`), DNG in `AsShotNeutral`. Decide: parse Canon ColorData + DNG in the Bridge, or ship without
- [x] One profile or several? (2026-11-14, an unseen client job): with 20 / 50 edited photos of the shoot the profile no longer matters — wedding profile 12 / 21 %, business profile 12 / 22 %, no model at all 15 / 23 % all-within. Profiles matter only with no or few own edits
- [x] **Learn from edits without a profile** (2026-11-15): edit request without `profile_id` (`learn_from_edits` + `format_type` then required; migration 013 makes `edit_results.profile_id` nullable) — the look comes from the selection's edited photos alone (per slider mean / in-shoot ridge / series by CV), sliders the examples lack are left out (RAW examples still on the camera's white balance pass on no Kelvin: the others keep theirs). Plugin: last entry in the apply dialog's profile list "No profile: only from the photos I already edited" (also when no profile is trained), clear hint when nothing in the selection is edited; automation `apply` without `profile`; folder mode `apply --learn-from-edits` without `--profile`. End to end on the 60 client job A photos (20 edited): every slider as good as with the profile, all sliders within tolerance 12/40 (with profile 7/40)
- [x] Culling on client jobs (2026-11-14; labels from the catalogs — export steps = delivered, ratings = chosen): ROC-AUC rules client job A 0.61 (exported, 84 %), dentist 0.55 (rated for retouch, 10 %); learning from the other job hurts (0.41 / 0.53) — "not delivered" and "chosen for retouch" are different decisions, so culling profiles must learn from the same kind of decision. Most catalogs hold only delivered photos (rejects deleted), so they carry no culling signal
- [x] EXIF exposure (EV from ISO/shutter/aperture) as a calibration signal: barely helps (barber exposure 58 → 69 %, elsewhere ±0) — not built
- [ ] Shoot calibration in Lightroom: re-applying to a selection Calotype edited before treats those photos as examples (no marker readable in the SDK) → mark applied photos (plugin metadata field) and leave them out
- [x] Profile "Business / Aufträge" on 4,900 photos of 6 clients (2026-11-14)
- [x] Final wedding profile "Hochzeit 2015–2019" on 13,338 photos of 11 weddings (2026-11-09); the trained shoots were removed from E: afterwards (originals on the NAS), their catalogs kept locally for the measurements
- [ ] Wedding archive: most 2017/18 shoots have neither XMP nor catalog on E: (disk full during the copy; one truncated CR2) → copy their `.lrcat` files from the NAS
- [x] License for the code: Apache-2.0 (2026-11-21); presets are CC0

### Lightroom Classic 16 (November 2026)

Checked against the "What's new" page and Lightroom 16.0's own presets (`Resources/Settings`) on 2026-11-15; process version stays 15.4, Camera Raw 19.

- [x] **Glow** ("Leuchten"): develop keys `Glow`, `GlowStyle` (0–4, five styles), `GlowSpread`, `GlowRange`, `GlowWarmth`, `GlowDirection`, `GlowDirectionalSoftness`; `getDevelopSettings` returns them on every photo (defaults 0 / 1 / 50 / 50 / 0 / 0 / 50), `applyDevelopSettings` sets them (verified in Lightroom 16.0, restored). Glow is part of the style layer (`style.py`), a ninth own look *Soft Glow / Sanftes Leuchten*, and XMPs write choices and amounts without sign like Adobe (`GlowStyle="2"`)
- [x] **Shoot look from the edited photos** (also for glow): with `learn_from_edits` the look settings most edited photos of the shoot share (tone curve, HSL, color grading, glow, grain, vignette, profile …; `shared_style`, ≥ half of them, no tie) go onto the other photos and win over the profile's preset. Folder mode: 20 examples with glow + color grading → all 40 photos got them, the sliders unchanged (12/40 all within)
- [x] **Lightroom's assisted culling as culling features** (2026-11-15): Lightroom stores its scores in the catalog (`AgLibraryImageCullingScore`: subject/eye sharpness, eyes open, exposure/misfire; `AgLibraryImageBestFrameScore`: aesthetic, face, frame, combined; `AgLibraryImageUndesiredScores`: blur, over/under exposure, ground shot). The plugin sends `catalog_path` with a cull job, the Bridge reads the scores (`catalog::culling_scores`, SQLite read-only *without* `immutable` — the open catalog is in WAL mode and fresh scores sit in the `-wal` file) into `lr_metadata.lr_culling`; the learned scorer uses them as extra features when ≥ 90 % of the job's photos have them, explanations name them ("Lightroom: sharp eyes"). Not in the starter rules yet: the value ranges (e.g. `eyesOpenState`) are unknown until a real run
- [ ] **Measure Lightroom's scores** against own decisions: run assisted culling on a rated shoot *without* applying flags/ratings, then `tools/eval/cull_lightroom.py` (rules vs. each Lightroom score without decisions; ours / Lightroom / both learned) — then decide starter rules from Lightroom's scores
- [x] **Learn from the photographer's AI masks** (done 2026-11-15 as shoot/profile median — per photo would add little: shoot median 3.9 / 5.7 slider points off for shadows / highlights, no mask 16.5 / 18.2): subject / sky / background masks are semantic, so they transfer to other photos (Lightroom recomputes them). Learn their correction values (e.g. subject shadows) per photo like the 10 sliders, or take the shoot's mask setup with `learn_from_edits`. Write path verified in Lightroom 16.0 (2026-11-15, automation `mask_probe`): apply our retouch preset, `updateAISettings`, then change only the correction values with `applyDevelopSettings` — values arrive, the mask stays computed. Not via a runtime preset (`addDevelopPresetForPlugin` with only the mask set the white balance to 1500 K / -150). The maintainer's catalog: 1,966 of 2,361 photos carry a per-photo "Subject Mask" from another tool (shadows +0.15 … +0.28) — another tool does predict it per photo (yardstick only)
- [ ] **History cleanup** (new: delete history steps, also scheduled): the catalog reader takes "edited" from the last history step — after a cleanup the photo may look unedited. Check what a cleaned-up photo leaves in `Adobe_libraryImageDevelopHistoryStep` and fall back to comparing settings with the untouched state (`edited_photos`)
- [ ] **Focus points** (Canon / Nikon / Sony): Lightroom shows the AF point; culling could measure sharpness *at the focus point* instead of the whole photo / face (AF info from the RAW maker notes, read by the Bridge)
- [ ] **Projection** (Upright, faces at the frame edges): no key in the presets and none on an untouched photo — find the key on a photo where it is set, then consider it for straighten
- [ ] **Depth range masks, skin blemish removal, masked color grading**: not in any bundled preset (depth and blemish removal are computed per photo); check whether a preset can carry them like the AI masks in `presets/retouch` — blemish removal would fit retouch

---

### Edit plan as one module (2026-11-24)
- [x] `plan_edit` (`services/workers/inference_worker/src/calotype_inference_worker/plan.py`): the edit job's domain logic in one place — examples vs. targets, shoot calibration, as-shot handling, series smoothing, look / preset / shoot look / crop / mask precedence; no queue, database or S3. The worker is load → plan → save; `tools/eval/shoot_lab.py` and `shoot_pool.py` run the same plan / EXIF parser, so the yardstick measures the production pipeline (same numbers on a synthetic pool)
- [x] Look composition in one place: `calotype_edit_serializer.compose` (prediction → preset or chosen Look → shoot look → straighten crop). "An own crop stays" is decided on the server now; each edit result says `kept_crop` (migration 015, API / Bridge / plugin contracts, optional); the plugin and `calotype-folder apply` only count it. Folder mode sends the crop keys of the photos to edit for that
- [x] Typed EXIF snapshot: `ExifSnapshot.from_snapshot` is the one parser (capture time, measured colour temperature, ISO / shutter / aperture / exposure compensation); contract `exif-snapshot-v1.schema.json`, referenced from `photo-upload-v1`
- [x] Folder mode sends the camera's exposure settings and measured colour temperature (`exif.rs`, Exif IFD of TIFF RAWs and the CR3 `CMT2` box, no new dependency), so camera-exposure features no longer switch off for folder-mode jobs
- [ ] Check the Exif reader on real Nikon / Sony / DNG files (tested on synthetic TIFF and CR3 structures only); ORF / RW2 headers are not read
- [ ] `calotype-folder apply` cannot send a Look (`base_preset`) yet

### One source per request field (2026-11-24)
- [x] Job requests and queue payloads defined once in `calotype_queue.payloads` (`TrainJobRequestV1` / `TrainPayloadV1` with `retrain`, `EditJobRequestV1` = `EditPayloadV1`, `CullJobRequestV1` = `CullPayloadV1`): the API validates with them, the four workers read `envelope.payload` through them (an unreadable payload goes to the DLQ as `invalid_payload`); unknown fields ignored and logged. The rule "profile_id, or learn_from_edits + format_type" lives only in `EditJobRequestV1` (Bridge and plugin no longer check it; the plugin and folder mode always build valid requests)
- [x] Bridge passes through: train / edit / cull requests type only `schema_version`, `lr_catalog_uuids` (and the cull's `catalog_path`); every other field goes to the server unchanged (`#[serde(flatten)]`), no `deny_unknown_fields` there — a new server option needs no Rust change. This fixed `consistent_series`, which the Bridge used to reject
- [x] Failure code: `jobs.failure_code` (migration 016) from the worker's exception (`calotype_domain.FailureCode`: `no_examples`, `profile_not_ready`, `too_few_photos`, `processing_error`), in `GET /v1/jobs/{id}`, kept by the Bridge (`failure_code` in its job state, SQLite schema 4); the plugin picks its hint by the code and falls back to the old text match for older servers
- [x] Drift tests: `libs/queue/tests/test_payloads.py` (JSON schemas list exactly the request models' fields and required set) and the Bridge's `every_server_request_field_passes_through_the_bridge` (every schema field reaches the fake server)
- [ ] The photo upload (`bridge-photo-v1`) still has `deny_unknown_fields` in the Bridge — it builds the upload itself, so a pass-through needs a decision on what is forwarded

### Worker runtime, blob store, feature store (2026-11-24)
- [x] `libs/worker-runtime` (ADR 007): `run_worker(Worker(...))` owns the loop every worker repeated — envelope / wrong kind / payload → DLQ, RUNNING → COMPLETED or FAILED with short reason + failure code (+ the worker's `on_failure` in the same unit of work), progress, heartbeat (`/tmp/lr_ff_<name>_worker.heartbeat`), reaper per owned job kind, Redis retry. Each worker's `cli.py` is its handler + a short main; queue names, entry points, DLQ reasons and the job / profile status semantics unchanged
- [x] Stuck-job reaper moved from `calotype_persistence.reaper` (which imported the queue lib against the import matrix) to `calotype_worker_runtime.reaper`, over the `Store` interface
- [x] Blob store in `libs/io` (`S3BlobStore`, `MemoryBlobStore`): the one S3 client config (same env vars and defaults), the key layout (`photos/{id}.jpg`, `models/{profile}/model-{version}.joblib`, unchanged) and bucket creation; used by the API and all workers
- [x] Feature store (`calotype_worker_runtime.FeatureStore`): a photo's vector of a version — stored, or computed from the preview and stored (never a zero vector); used by the feature and the train worker
- [x] Workers on the `Store` interface (+ `feature_vectors`, job status / touch / stuck, photo analysis, profile status / artifact, `kept_crop`; `store_scope`, `MemoryStore.scope`); tests across the seams: the runner on `fakeredis` + `MemoryStore` + `MemoryBlobStore`, one handler suite per worker through the runner (the cull worker's tests run in CI for the first time)

## Phase 8 — Calotype 2.0 (next milestone)

Sources and what we take from each: [`docs/RESEARCH.md`](docs/RESEARCH.md).

### 8.1 Local inference on every machine
- [ ] ONNX Runtime for our own models, one execution provider per platform: CoreML (Apple Silicon), CUDA / TensorRT (NVIDIA), DirectML (AMD, Intel Arc/Iris), OpenVINO (Intel Core Ultra NPU), QNN (Snapdragon X), CPU fallback
- [ ] Embed it in the Bridge / Tauri app (`ort` crate) so photographers need no Python or CUDA install
- [ ] Measure speed on real hardware before publishing any figure

### 8.2 Own model from data we may use
- [ ] Backbone: DINOv2 / SigLIP / PE gave no gain over the hand features (Model v2) — the bottleneck is transfer across shoots, not the image encoder. Try a small backbone (MobileNetV4, ConvNeXt V2) only together with 8.3–8.5, measured with the contiguous-block and cross-shoot splits
- [ ] Synthetic training pairs: degrade licensed photos (exposure, white balance, tone) and render them through real Lightroom with our CC0 looks (`tools/lr_e2e`); the label is the slider change that undoes the damage (Deep Preset; ATune trains a slider-driving model without a single expert edit)
- [ ] Training data only from sources we may use: the maintainer's archive, MIT-Adobe FiveK and PPR10K (check each licence for the intended use), freely licensed photos. Never another tool's models or outputs as a teacher
- [ ] Pooled base model + per-photographer layer (hierarchical, Saeedi et al.) — formalises today's pooled base model (R6 white balance 14 → 32 % with 20 own photos)

### 8.3 Consistent series without flicker
- [x] Shoot consistency as a graph optimisation in slider space (HaCohen et al.), first version 2026-11-21: `calotype_inference_pipeline.series` links photos close in capture time (≤ 20 s) *and* alike in their feature vectors, a quadratic cost pulls exposure / temperature / tint of each series together, edited examples are fixed (an example still on as-shot white balance anchors no white balance). Edit request `consistent_series` (default off), solved per connected series with numpy
- [x] `consistent_series` in the plugin's apply dialog ("Keep series consistent", default off), the automation channel (`consistent_series`) and `calotype-folder apply --consistent-series` (2026-11-24; the Bridge passes it through since task D)
- [ ] Tune the link thresholds (`MAX_GAP_SECONDS`, `FEATURE_SCALE`, `STRENGTH`) on real shoots — so far only synthetic tests
- [ ] Yardstick: spread of the predicted sliders within a series vs. the photographer's own spread (PPR10K's group-level consistency) — `series.spread()` computes it; the measurement is open

### 8.4 White balance relative to as-shot
- [x] The camera's *measured* colour temperature as a feature (2026-11-21): on shoots with a fixed camera setting ("Daylight") as-shot is the same on every photo and carries nothing, but Canon stores its automatic estimate per frame (`ColorTempMeasured`). The Bridge reads it from the RAW (`whitebalance.rs`: CR2 MakerNotes, CR3 `CMT3` or the `CTMD` track; identical to ExifTool on 2,064 + 618 real files from a 5D Mark IV and an R6 Mark II) and sends it as `exif_snapshot.wb_measured_kelvin`; `shoot.calibrate` adds it to the features for temperature. Two yardstick shoots, temperature within 150 K with 10 / 20 / 50 examples: wedding 24.4 / 30.8 / 42.3 → 32.8 / 35.5 / 48.6 %, kindergarten 42.5 / 47.6 / 60.8 → 42.8 / 51.5 / 65.0 %; all six sliders: 8.5 / 12.7 / 21.0 → 11.0 / 15.0 / 24.0 % and 15.7 / 21.8 / 35.6 → 15.9 / 23.0 / 36.4 %. As a fixed offset to the measurement it failed (kindergarten 47.6 → 24.5 %)
- [ ] Other ColorData versions (only 13 and 48 are checked on real files), other makers (Nikon, Sony, Fuji) and DNG `AsShotNeutral`
- [ ] The measurement in training a profile (today only in shoot calibration)
- [ ] Target = mired offset from as-shot instead of absolute Kelvin
- [x] White balance per photo instead of per profile (2026-11-23): photos on the camera's white balance teach their Kelvin too; at apply time a photo keeps "As Shot" when the prediction is within 15 mired of the camera's (`AS_SHOT_MIRED`), else gets its own Kelvin. Marryween (camera fixed at 5899 K, hut lit by lamps at ~2850 K): hut photos the model never saw 2624 → 491 K off, daylight 11 / 11 stays as shot. Old artifacts keep their profile-wide flag
- [ ] Measure the per-photo decision across the maintainer's weddings with `tools/eval` (the profile-wide rule of #23 came from such a measurement: predicted Kelvin on unseen weddings within 150 K for only 13-27 %) before merging to main; 30 of 1,673 Marryween photos got 5,300-5,900 K just outside the tolerance
- [ ] Map neutral to the photographer's preferred white balance with a tiny model (Zhao, Afifi & Brown: ~500 parameters)
- [ ] Adapt to the camera from the shoot's unlabeled photos (C5) or from the colour matrices in the RAW / DNG metadata (CCMNet)

### 8.4b One living profile
- [x] Retrain a profile in place (2026-11-23): train request `profile_id` merges the profile's earlier training photos (read with their *current* settings, so corrections are learned) with the new ones; the profile keeps its id and stays usable, a failed retrain keeps the old model. `untouched` (Lightroom key -> value) names a preset's placeholders (Marryween: highlights -100 on 128 of 300 photos): such a slider is left out of that photo's target, every other slider still learns from it (`calotype_edit_serializer.training`, per-slider masks in `train_model_v2`)
- [x] Plugin: "keep training an existing profile" in the train dialog (2026-11-24): the train dialog offers "New profile" or "Keep training: <ready profile>" (name, genre and colour then come from the profile); an optional "Import preset" turns that preset's slider values into `untouched` placeholders (`LookPresets.placeholders`, neutral 0 left out) — chosen instead of guessing placeholders from how many photos share a value, which would also drop a recipe's constants
- [x] Accepted photos as feedback (2026-11-24): the photographer chooses a marker (none / colour label / minimum stars), kept on the profile (`accepted_marker`, migration 017) and preselected next time; the plugin sends the selected photos carrying it (`accepted_lr_catalog_uuids`). No self-learning: the train worker skips a photo whose settings still hold Calotype's latest result for it (any profile; compared on the sliders that result set) unless it is accepted; corrected photos and photos Calotype never edited are learned as before; earlier training photos of a retrain pass the same check and keep their acceptance
- [x] Delete / rename profiles (2026-11-24): `PATCH` / `DELETE /v1/profiles/{id}` (soft delete, `deleted_at`: hidden from list, apply and retrain; data and S3 artifacts stay), Bridge forwards them, plugin menu "Manage profiles"; automation `profiles`, `rename_profile`, `delete_profile`, `train` with `marker` / `import_preset`
- [ ] Not yet in a real Lightroom: the new train dialog, "Manage profiles" and a retrain with a marker (`tools/lr_e2e`)

### 8.5 Look from few examples
- [x] Choose the closest examples by image content, not only capture time (RefRetouch), first version 2026-11-21: without a profile `shoot.calibrate` uses `blend` (half ridge, half the three references closest in feature space) and only chooses between it and `series`. Two shoots edited by other tools (internal yardstick, `tools/eval/shoot_lab.py`), all six sliders within tolerance with 10 / 20 / 50 examples: wedding 6.1 / 9.6 / 14.5 → 8.5 / 12.7 / 21.0 %, kindergarten 12.8 / 17.2 / 23.4 → 15.7 / 21.8 / 35.6 %
- [x] With a profile (2026-11-21): measured for the first time — the old cross-validated choice among mean / profile offset / ridge was clearly *worse* than no profile at all (all six sliders within tolerance, mean of six cases: 15.3 % vs 21.9 %; temperature 38 % vs 46 %). Now the profile's prediction is one more feature of `blend` for every slider (after Saeedi et al.: shared model, adapted per shoot): 22.5 %. The "profile" in the test was a boosting model trained on the other yardstick shoot
- [x] **First measurement on the maintainer's own edits** (2026-11-21): three own shoots with their catalogs (read-only; `cargo run --example pool` + `tools/eval/shoot_pool.py` build the pools, kept local). Own edits vary far more within a shoot than the yardstick shoots (exposure std 0.3–0.8 EV, temperature 480–1,250 K), but most photos share the synced edit of their scene — so *with capture times* (the plugin always sends them) the closest edited photo carries almost everything. All ten sliders within tolerance, 10 / 20 / 50 examples, state of the morning → now, both with times: large shoot (700 edited photos) 69 / 73 / 80 → 67 / 73 / 80 %; small shoots 45 → 45 % (10 of 20) and 29 / 33 → 35 / 44 % (10 / 14 of 27); yardstick wedding 9 / 10 / 17 → 12 / 17 / 27 %, yardstick kindergarten 12 / 19 / 25 → 15 / 19 / 33 %. Without times the same shoots look far worse (large own shoot 2–11 %) — measurements without times understate scene-wise editing
- [x] `blend+scene` (2026-11-21): the cross-validated choice between `blend` and `series` is replaced by a fixed rule — a photo within two minutes of an edited one takes its values, the others `blend`. Mean of twelve cases 36.9 → 39.0 %; tried and worse: per-slider cross-validation with a time limit (33–37 %), deciding from how much the examples of one scene agree (32–37 %), smoothing white balance over the series graph (17 %), a scene kernel (15–18 %). Price: the kindergarten shoot edited per photo by another tool loses 1–4 points
- [x] **Run in a real Lightroom 16** (2026-11-22, 16 photos of a wedding, 8 as examples, the other 8 reset and re-applied with `learn_from_edits`, all restored): 8 results in 42 s, Lightroom holds exactly the predicted values, capture time / measured light / camera exposure arrive. Found and fixed: applying removed *all* our masks from earlier runs and re-added only the kinds of this run — three photos lost their sky mask. Now only the kinds that are added again are replaced (checked in Lightroom 16 with plugin 0.3.2 on 2026-11-22: a photo with subject, background and sky masks, subject and background applied again — the sky mask stays, values and all other settings unchanged)
- [x] `same` (2026-11-21): a slider two thirds of the examples carry with the identical value stays exactly there — found on the own shoot, where `blend` moved a synced contrast (within tolerance 80–86 % → 97 %); none of twelve cases got worse
- [x] Highlights and blacks that change from photo to photo (2026-11-22; in the Lightroom 16 run they were the two sliders outside tolerance, 3 and 2 of 8 photos): two ideas measured on the five shoots, neither is in. Snapping a slider to one of the values the examples carry, when the examples share few values (nearest value / the example closest in time / closest in content): mean of twelve cases 38.7 → 38.8–39.1 %. Giving the tone sliders the brightness percentiles as extra-weighted features, like the camera values for exposure: no slider moves by more than a point. With a handful of examples the shoot calibration has nothing left to learn there — sliders set per photo need a profile trained on the photographer's archive
- [x] A profile from the maintainer's archive as help for a new shoot (2026-11-22): twelve own shoots (nine weddings, three client jobs, 16,000 photos; settings and features read from the local database, no capture times there), each predicted with a boosting profile trained on the other eleven plus 10 / 20 / 50 examples of its own. All ten sliders within tolerance, mean of the twelve: without profile 13.7 / 16.2 / 19.9 %, profile as a feature (as built) 13.8 / 16.7 / 19.6 %, a profile that learns only each photo's deviation from its shoot's mean as a feature 13.9 / 16.3 / 19.9 %, that deviation added straight to the examples' mean 3.2 / 4.1 / 4.4 %. So a profile adds nothing once a shoot has examples; what is missing there are exposure (47-54 % within tolerance) and temperature (34-41 %), the two sliders the scene rule carries when capture times are known (own shoot with times: 67-80 % all sliders). Next step is therefore capture times for the archive, not a bigger profile
- [x] The scene rule on whole weddings (2026-11-22): 40 of the maintainer's catalogs (30 weddings 2019-2023 with 23,800 edited RAW photos, ten client and portrait jobs), read-only, edits and capture times only — no image features, so everything outside a scene falls back to the examples' mean and this is a lower bound for the pipeline. All sliders within tolerance with 10 / 20 / 50 examples spread over the shoot: weddings 28.8 / 33.4 / 41.0 % (mean of the examples alone at 20: 24.7 %), all 40 shoots 34.0 / 39.4 / 47.4 %. With 20 examples 60 % of a wedding's photos lie within two minutes of one; of those 39 % are right, of the others 23 %. The time limit hardly matters (30 s 31.7 %, 2 min 33.4 %, 10 min 33.9 %). Weddings with a set white balance (13) reach 17 % — exposure 39 % and temperature 47 % within tolerance, blacks 74 %, highlights 75 % —, weddings left on the camera's white balance (17, temperature not scored) 46 %, there only exposure is open (51 %). On four weddings copying the closest example is worse than the mean (edits nearly constant, the odd deviating example gets copied)
- [x] The scene rule per slider (2026-11-22): seven of the own weddings measured with the real pipeline (previews from the first 4 MB of each RAW file on the archive, 3,700 edited photos; pools kept local). There copying the closest example helps white balance a lot and hurts exposure a little (exposure within tolerance 53 % with the rule, 57 % with `blend` alone; temperature 69 vs. 54 %). Now white balance follows the closest edited photo for ten minutes, and for exposure that photo's weight fades with the time between (1/e after a minute, the rest `blend`). All sliders within tolerance, 32 cases on 13 shoots (10-50 examples): 32.0 → 33.2 %, weddings 28.7 → 30.7 % (15 of 21 cases better, 3 worse; the one wedding not used for tuning: exposure +2-3 points, temperature +5-12, all sliders -1.5 to +0.8), own portrait shoots 60.0 → 59.2 %, the two yardstick shoots 20.1 → 20.5 %. Tried and not in: correcting the copied exposure by the brightness difference to the example (own shoots 20-40 points worse), a small brightness-and-camera model for exposure outside scenes (+0.5), a shorter hard limit for exposure (good on weddings, bad on portraits)
- [x] Start from zero (2026-11-22): apply option that first resets every selected photo — sliders, curves, color mixer, color grading, grain, vignette, sharpening, crop, masks and local corrections; lens corrections, transform and spot removal stay — so the result is exactly the profile's values plus the look, nothing left from an earlier edit (found on a wedding that carried another preset's color grading under the new look). Needs a trained profile (after a reset nothing in the selection is an example), excludes learning from edits, asks for confirmation, keeps the state before as a dated snapshot per photo; automation `apply` takes `fresh`, command `fresh` resets only
- [x] **Editing a fresh shoot without any example: profiles keep the recipe** (2026-11-22). A profile from seven of the own weddings, applied to a new one, was useless (temperature 1,400 K off, blacks +56), and its exposure was worse than leaving the slider alone (within 0.15 EV: profile 15 %, zero 36 %, the wedding's own mean 45 %; each wedding predicted from the other six). Cause, read from 30 own catalogs: the weddings follow three fixed recipes — 85-100 % of a wedding's photos carry contrast, highlights, shadows, whites and blacks with exactly the same values, only the exposure changes per photo — and one model over all ten sliders averages the recipes into values none of them has; the exposure level belongs to the recipe (0.0-0.1 with one, 0.5-0.9 with another). Now a slider 60 % of the training photos share is stored as a constant of the profile and wins over the model (`recipe_constants`), and a profile whose training photos kept the camera's white balance in at least four of ten cases predicts no temperature and tint (a predicted Kelvin was within 150 K for 13-27 % of an unseen wedding's photos). Within one recipe exposure without examples is within 0.15 EV for 46-62 % of the photos (three weddings, each from the other two) — as good as with 10-50 examples. Calibration from examples still works for sliders a profile leaves out
- [x] **First review of a wedding edited without examples** (2026-11-22, matte recipe, the maintainer went through 225 photos and corrected them): 114 of 225 kept tone and white balance exactly as set, 53 % within tolerance on all six tone sliders with the white balance kept. Per slider within tolerance: exposure 68 % (92 changed, median 0.38 EV, as often up as down), highlights 63 % (84 raised from the recipe's -100 to a median of -46), shadows 89 %, blacks 91 % (changed ones 10 darker), whites 94 %, contrast 97 %; white balance set by hand on 38 (mostly one Kelvin value copied over a series, 3200-4000 K indoors). Of 37 straightened photos 10 were turned back (angles of 1-2.7 degrees in one indoor series reduced to 0.25). Bug found by it: a look read from a Lightroom preset carried `CameraProfile = "Default Profile"` (Lightroom's placeholder when the preset names no profile) and replaced the camera profile on every photo; the placeholder is dropped now and the Wedding Emotional look names Adobe Standard as the maintainer's weddings do
- [ ] From that review: a recipe constant at the end of the scale (highlights -100) is the usual case, not the rule — predict when a photo leaves it (bright windows, dresses) instead of fixing it for all; white balance for indoor series; straighten angles above 1 degree need stronger evidence indoors; corrections are copied over series, so a correction on one photo should carry to its neighbours in time
- [ ] Recipes: find them when training from an archive (cluster the shoots by their constant sliders, one profile per recipe) instead of leaving the choice of shoots to the user; white balance relative to the camera's for profiles that do predict it; exposure model with the camera's exposure settings
- [ ] Exposure stays the open slider on weddings (50-70 % within 0.15 EV), then blacks and contrast on weddings edited per photo
- [ ] Temperature on the yardstick wedding stays the weakest slider (31–50 % within 150 K); on own shoots it is 55–84 % with times
- [x] Tried without gain (2026-11-21, same six cases): a direct affine map from the camera's measured white point to the edited one (Zhao, Afifi & Brown, reduced to what 20 examples allow) — temperature 30–42 % against 46 % with the measurement as a feature; examples augmented with exposure-damaged copies of their previews (ATune / Deep Preset in the small, ±0.25 … ±1 EV) — exposure 45.6–48.9 % against 49.0 %
- [ ] Exposure and temperature stay the weak sliders (40–68 % / 24–61 %): next lever is white balance relative to as-shot (8.4)
- [ ] Content-aware style per photographer instead of one look for all photos (Kosugi & Yamasaki)

### 8.6 Culling
- [ ] Series-relative ranking; the human preference data of Chang et al. as a second yardstick next to the photographer's exports

### 8.7 Local training in the desktop app
- [ ] The photographer picks 30–50 edited RAWs, Calotype trains the personal layer locally (GPU / NPU / CPU)

### 8.8 Community Profile Package & Sharing (`.calotype-profile`)
- [ ] **Package format (`.calotype-profile`)**: Portable bundle (ZIP) containing `profile.json` (metadata, genre, author, license), `model.joblib` (trained regressors for exposure, WB and tone), `style.xmp` (the signature look curve, HSL, grading) and optional `retouch.json` (learned AI mask strengths).
- [ ] **Rights & Consent Confirmation (Checkbox)**: Mandatory check during export and community publishing: *"I confirm that I own the rights to this editing style/training data and that no third-party terms or models were violated."*
- [ ] **One-Click Import & Export**:
  - Export: Bridge / Plugin UI button "Export Profile" generates a `.calotype-profile` file to share.
  - Import: Drag-and-drop into Desktop App or "Import Profile" in Lightroom plugin installs it instantly into ready profiles.
- [ ] **Community Profile Hub**: Open repository directory and web index on `calotype.xyz` for community-curated styles.

### 8.9 Official Bundled Starter Profiles
- [ ] Train official out-of-the-box profiles (**Wedding Emotional**, **Wedding Golden Light**) on the maintainer's real wedding RAWs once provided.
- [ ] Ship the pre-trained artifacts embedded in the Bridge release so new users get instant AI exposure, white balance and look without training first.

---

### Backlog / Nice-to-have
- [x] **API tests across a real seam** (2026-11-24): routes get their data through `Depends(get_store)` (`calotype_persistence.stores`); tests override it with `MemoryStore` (real ORM records) instead of patching ~15 repository methods by import path; store contract suite runs against memory and — with `CALOTYPE_TEST_DATABASE_URL` — Postgres
- [x] CI Postgres service (2026-11-24, worker-tests job; locally 56 / 56 against a throwaway `calotype_test` database) (`services: postgres` with pgvector + `alembic upgrade head`) and `CALOTYPE_TEST_DATABASE_URL` set, so the Postgres half of `libs/persistence/tests/test_store_contract.py` runs in CI
- [x] Workers on the `Store` interface (2026-11-24, ADR 007): handler tests use `MemoryStore` + `MemoryBlobStore`, no monkeypatching
- [ ] **Idea: a pixel step — sharpen, restore, upscale** (2026-11-22, not started; what exists today comes first). A new building block: Calotype so far only writes sliders, this would render a new file next to the original and add it to the catalog. First look at the field, licences read from the repositories, quality claims from the papers and not measured by us: upscaling is the mature part (faithful: HAT, Apache-2.0, or DRCT, MIT; with generated detail: SeedVR2, Apache-2.0, or one-step diffusion like OSEDiff, Apache-2.0 on Stable Diffusion 2.1 weights whose own licence needs a check); restoring and denoising: NAFNet (MIT; fast) or Restormer (MIT; heavier), both trained on action-camera blur and phone noise, so weak on lens softness and missed focus — denoising belongs on the RAW data, which Lightroom already does; sharpening real photos is the gap (DeblurDiff, MIT, NeurIPS 2025, is a diffusion model and slow). Load weights through spandrel (MIT) instead of single research repositories. Not usable for us: SUPIR, HYPIR, InvSR, CodeFormer (non-commercial), Upscayl (AGPL). First step would be a test of three or four candidates on own photos (one soft, one noisy, one small), every model through `THIRD_PARTY_MODELS.md`
- [ ] "Start Bridge" menu item in the plugin that starts the Rust Bridge (`calotype-bridge-headless`) when it is not running
- [ ] More sliders per photo: Texture, Clarity, Dehaze, tone curve, HSL (today only via the profile's or the shoot's look)
- [ ] Ruff upgrade: CI pins 0.8.1; 0.17 reports 49 findings (14 × B008 = FastAPI `Depends`, ignore via config; imports, blind excepts)
- [ ] Other raw converters: RawTherapee / darktable sidecars, Capture One (needs an ADR)
- [ ] Add a `GET /v1/jobs` list endpoint with pagination and status filter
- [ ] Profile versioning: bump `version` on retrain instead of overwriting artifact
- [ ] S3 presigned URLs for returning edit result images (not just `lr_settings`)
- [ ] Admin endpoint to manually set Profile status (e.g. force `ready` for testing)
