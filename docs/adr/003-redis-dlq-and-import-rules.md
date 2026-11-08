# ADR 003 — Redis lists, DLQ and import rules

- **Status:** Accepted
- **Date:** 2026-05-01
- **Deciders:** Maintainer

## Context

Jobs must be transported reliably between the API and several worker processes; malformed payloads and exceptions must not be dropped silently.

## Decision — Redis topology

- **Transport:** Redis **lists** with `RPUSH` / `BLPOP` and known keys [`QUEUE_TRAIN`](../../libs/queue/src/calotype_queue/constants.py), `calotype:jobs:feature`, `calotype:jobs:inference` (see `libs/calotype_queue`).
- **Routing:** `train` goes directly to `calotype:jobs:train`; `edit` first to `calotype:jobs:feature`; after a successful stub step the feature worker forwards it via `forward_to_inference` to `calotype:jobs:inference`.
- **DLQ:** Every primary queue has a dead-letter key `primary:dlq`; invalid envelopes and hard processing errors are stored there with JSON metadata (see `push_dead_letter` in `calotype_queue.consumer`).
- **Evolution:** Streams/consumer groups or an orchestration framework (Temporal etc.) remain swappable behind a publisher/consumer abstraction in `libs/queue`.

## Decision — module import matrix

| Module | Allowed dependencies |
|-------|-------------------------|
| `calotype_domain` | no internal LR packages |
| `calotype_queue` | domain, pydantic, redis |
| `calotype_persistence` | domain, sqlalchemy/psycopg |
| `calotype_inference_pipeline` | stdlib only, optionally numpy/torch later |
| `calotype_observability` | stdlib logging |
| `services/api` | domain, persistence, queue (no workers, no torch) |
| `services/workers/*` | domain, persistence, queue, observability, inference-pipeline if needed |

Prohibitions: workers do **not** import `calotype_api`; the API does **not** import worker modules.

## Consequences / trade-offs

- **Positive:** Simple debugging, minimal operational surprises, clear escalation path via the DLQ and `jobs.failure_reason`.
- **Negative:** Lists offer fewer built-in retries than streams; horizontal scaling requires our own idempotency on consumption (here: `job_id` + status in Postgres).
