# tarsier-queue

Redis lists (`RPUSH`/`BLPOP`) and **`JobEnvelopeV1`** — canonical schema at [`packages/contracts/json-schema/job-envelope-v1.schema.json`](../../packages/contracts/json-schema/job-envelope-v1.schema.json).

## Dead letters / DLQ

Every primary queue `tarsier:jobs:*` has a dead-letter key `{queue}:dlq`. Invalid payloads at parse time and hard errors during processing end up there (see `tarsier_queue.consumer.push_dead_letter`) — decisions in [ADR 003](../../docs/adr/003-redis-dlq-and-import-rules.md).
