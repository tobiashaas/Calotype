# ADR 007 — Worker runtime, blob store and feature store

- **Status:** Accepted
- **Date:** 2026-11-24
- **Deciders:** Maintainer

## Context

The four workers (feature, train, inference, cull) each repeated the same skeleton in
`process_one`: BLPOP → unreadable envelope to the DLQ → wrong job kind to the DLQ → payload
model → job RUNNING → progress per photo → COMPLETED, or FAILED with a short reason and a
failure code and the envelope to the DLQ. Each `main()` had its own heartbeat path, Redis retry
loop and reaper start (the inference worker none, explained only by a comment). None of the
`process_one` functions had a test: they called the repositories' static methods with a
session and boto3 directly, so only monkeypatching could reach them.

S3 access was spread the same way: a `_s3_client()` in every worker plus the API's
`storage.py`, each with its own defaults; bucket creation twice with different exception
handling; the object key layout split between the API (`photos/{id}.jpg`) and the train /
inference workers (`models/{profile}/model-{version}.joblib`). "The photo's vector of this
version, else download the preview, compute, reject an empty vector, store" existed twice
(train worker, feature worker). And the stuck-job reaper lived in `calotype_persistence`,
importing the queue library against the import matrix of ADR 003.

## Decision

1. **New library `libs/worker-runtime`** (`calotype_worker_runtime`). A worker is a
   `Worker(name, queue, kind, payload_model, handler, reaper_kinds, on_failure,
   compute_features)`; `run_worker(worker)` is its whole main loop and `process_one(worker,
   services)` one message. The runtime owns the envelope, the DLQ reasons (`invalid_envelope`,
   `unexpected_job_kind:<kind>`, `invalid_payload`, `processing_error`), the job status
   transitions, the failure reason (`Type: message`, ≤ 500 characters) and code
   (`failure_code(exc)`), the heartbeat file (`/tmp/lr_ff_<name>_worker.heartbeat`), the Redis
   retry and the reaper for the job kinds whose pipeline starts on the worker's queue. The
   handler gets a `JobContext`: the typed payload, `store()` (a unit of work over the `Store`
   interface), `blobs`, `features`, `progress()`, `complete(store)` (COMPLETED together with the
   handler's last writes), `forward_to_inference()` and `log`; it returns or raises. Worker
   specifics stay in the handler and its `on_failure` (the train worker: a failed retrain keeps
   the profile READY, otherwise FAILED — in the same unit of work as the job's FAILED).
   - **May import:** domain, persistence, queue, observability, io (pydantic and redis through
     queue).
   - **Imported by:** the workers only — never the API.
2. **`libs/io` is the blob store** (`calotype_io`, stdlib + boto3): interface `BlobStore`
   (`preview`, `put_preview`, `model`, `put_model`), adapters `S3BlobStore.from_env()`
   (S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY; defaults as before:
   `http://127.0.0.1:9000`, `calotype-photos`) and `MemoryBlobStore`. It owns the key layout and
   bucket creation. Writes return the key, which the caller stores on the record; reads take the
   key the record holds, so every existing object is found byte for byte. Imported by the API
   and the workers.
3. **Feature store** (`calotype_worker_runtime.FeatureStore`): `vector(store, photo, version)`
   = the stored vector, or computed from the preview and stored; None (and nothing stored) for a
   missing or undecodable preview. The function that computes the vector is passed in by the
   worker (`compute_features` from inference-pipeline), so the runtime does not import the ML
   library.
4. **Workers on the `Store` interface.** The interface gains what the workers write
   (`feature_vectors`, job `set_status` / `touch` / `find_stuck` / `reset_to_queued`, photo
   `merge_analysis` / `set_feature_vector_id`, profile `set_status` / `set_artifact`, edit result
   `kept_crop`) plus `store_scope(factory)` (one session per unit of work) and
   `MemoryStore.scope()`; the contract suite covers the additions. The reaper moves to
   `calotype_worker_runtime.reaper` and works over the `Store`.

Import matrix additions (ADR 003 otherwise unchanged):

| Module | Allowed dependencies |
|-------|-------------------------|
| `calotype_io` | stdlib, boto3 |
| `calotype_worker_runtime` | domain, persistence, queue, observability, io |
| `services/api` | domain, persistence, queue, io |
| `services/workers/*` | domain, persistence, queue, observability, io, worker-runtime, inference-pipeline, edit-serializer (`cull_worker` also culling) |

## Consequences / trade-offs

- Positive: one place for the job lifecycle — a new worker is a handler; every worker is
  testable through the real runner with `fakeredis` + `MemoryStore` + `MemoryBlobStore` (the
  cull worker had no test before); one S3 configuration and one key layout; the import
  violation of the old reaper is gone.
- Same behaviour for Lightroom, the Bridge and the API: queue names and messages, console
  scripts, DLQ reasons, DB rows and S3 keys are unchanged. Small differences inside a job: the
  runner sets RUNNING in its own transaction (the train worker sets its profile TRAINING right
  after, no longer in the same one); the inference worker builds its edit request inside the
  handler, so a malformed one now fails the job instead of escaping the loop; the dead-letter
  warning is logged by every worker, not only the feature worker.
- Negative / risks: one more library in the workspace and in CI; `fakeredis` (BSD-3-Clause) as a
  dev dependency; a worker that needs another per-process resource (like the cull worker's face
  analyzer) opens it in its `main()` and closes over it in the handler.
