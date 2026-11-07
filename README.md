# LR-FrameFlow

Modular system for **AI-assisted Lightroom Classic editing**: a Lightroom plugin for workflow and review, a **Bridge desktop app** for local orchestration, a **thin API** (FastAPI) and **workers** for features, training and inference, with a clearly versioned **contract** between all parts.

- **Upstream:** [github.com/tobiashaas/LR-FrameFlow](https://github.com/tobiashaas/LR-FrameFlow)

## Architecture (short)

```text
Lightroom Plugin (Lua) → Bridge (Desktop) → API → Job Queue → Worker (Feature / Train / Inference)
                                                                    ↓
                                              Postgres (+ pgvector), object storage
```

See package boundaries and decisions in [`docs/adr/`](docs/adr/) (including queue, Tauri, Redis/DLQ).

## Repository layout

```text
apps/
  lr-plugin/           # Lightroom Classic SDK plugin (Lua)
  bridge/               # Local Bridge app (Tauri – see ADR)

packages/
  contracts/           # JSON Schema + OpenAPI (Bridge ↔ API); CI should run contract tests

services/
  api/                  # FastAPI gateway (jobs, no heavy inference in the request path)
  workers/             # Feature, train, inference workers (scalable)

libs/
  domain/               # JobKind/JobStatus (no infra imports)
  persistence/          # SQLAlchemy, repositories (loads domain)
  queue/                # Redis, JobEnvelopeV1, DLQ helpers
  observability/        # structured logs
  inference-pipeline/   # pure inference steps (stub)
  edit-serializer/      # Lightroom-compatible writeback
  lr-io/                # Shared I/O and path helpers

infra/
  compose/             # local Postgres (pgvector), Redis, MinIO
  migrations/           # Database migrations

docs/
  adr/                  # Architecture Decision Records
```

## Contracts & CI

- Source of the API and data formats: [`packages/contracts/`](packages/contracts/) (OpenAPI + JSON Schema).
- **Recommendation:** add a CI step that validates the schemas (`openapi-spec-validator`, `check-jsonschema`) and runs **contract tests** between Bridge client stubs and types generated from the spec — not automated yet, but documented in the spec folder.

## Start local infra

Prerequisite: [Docker Compose](https://docs.docker.com/compose/).

```bash
cd infra/compose
docker compose up -d
```

Environment variables: see the comments in [`infra/compose/docker-compose.yml`](infra/compose/docker-compose.yml). For the API/workers there is an example file in [`infra/compose/env.example`](infra/compose/env.example).

## Python components

Every Python component has its own `pyproject.toml` (clear ownership). Install order matters because of the inference worker's dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e "libs/domain" -e "libs/persistence[dev]"
pip install -e "libs/queue" -e "libs/observability"
pip install -e "libs/edit-serializer" -e "libs/lr-io" -e "libs/inference-pipeline[dev]"
pip install -e "services/api[dev]"
pip install -e "services/workers/feature_worker" -e "services/workers/train_worker" -e "services/workers/inference_worker"

cd services/api
uvicorn lr_frameflow_api.main:app --reload
```

After starting Postgres/Redis (Compose), run the migration: see [`infra/migrations/README.md`](infra/migrations/README.md). Check contracts locally: `python scripts/validate_contracts.py`.

## Bridge (Tauri)

Folder [`apps/bridge`](apps/bridge): minimal scaffold; complete the app with `pnpm create tauri-app` (see `apps/bridge/README.md`).

## License

Unless marked otherwise, see `LICENSE` in the repo root (optional, to be added).
