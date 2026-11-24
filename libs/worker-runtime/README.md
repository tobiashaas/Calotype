# calotype-worker-runtime

The loop around every worker's job (ADR 007): `run_worker(Worker(...))` takes envelopes from
the worker's queue, dead-letters what it cannot run, sets the job RUNNING / COMPLETED / FAILED
(short reason + failure code), touches progress, writes the heartbeat, runs the stuck-job
reaper and retries when Redis is gone. The handler gets a `JobContext` (typed payload, store,
blob store, feature store, `progress()`, log). Also: `FeatureStore` (a photo's feature vector,
stored or computed and stored).

Imports: domain, persistence, queue, observability, io. Imported by the workers only, never by
the API. Tests run on `fakeredis` + `MemoryStore` + `MemoryBlobStore`.
