# ADR 001 — Asynchronous job orchestration via a queue

- **Status:** Accepted
- **Date:** 2026-05-01
- **Deciders:** Maintainer

## Context

The Lightroom pipeline consists of expensive steps (features, embedding, retrieval, inference). A synchronously blocking FastAPI handler would risk timeouts and prevent scaling.

## Decision

- FastAPI returns **HTTP 202** with `job_id` and persists payload + states in Postgres (`jobs` later via migrations).
- Long-running steps run **asynchronously** in dedicated **worker processes**, connected via **Redis as a queue** (`REDIS_URL` in [`infra/compose/env.example`](../../infra/compose/env.example)). Alternatives such as Temporal can be evaluated later without losing modularity.

## Consequences / trade-offs

- **Positive:** Horizontal scaling for `inference_worker`, clean separation of API vs. work, retries with less coupling possible (Idempotency-Key header).
- **Negative:** Additional operations (Redis), more local complexity compared with everything-in-process — but this matches the scaling goal from the product concept.
