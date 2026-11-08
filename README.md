# LR-FrameFlow

Open-source, AI-assisted editing and culling for **Lightroom Classic**. LR-FrameFlow learns *your*
style from photos you have already edited and *your* taste from photos you have already rated —
and it runs on your own machine.

- **Edit profiles:** train a profile from finished edits, apply it to new photos (exposure, white
  balance, tone, presence per photo; a fixed look — curve, HSL, color grading — on top).
- **Straighten:** levels photos that have clear reference lines (walls, door frames, horizon) with
  the largest crop, like Lightroom does; photos you cropped yourself keep their crop.
- **Culling:** sorts a shoot into *Keep / Check / Sort out* with a reason per photo ("best of its
  series", "eyes closed", …). It learns from the stars and flags you already gave; without them it
  uses explainable starter rules. Nothing you set is overwritten — results are collections.
- **Folder mode:** the same without Lightroom, on RAW + XMP folders (`lrff-folder train / apply /
  cull`), optionally writing into a separate output folder.

- **Upstream:** [github.com/tobiashaas/LR-FrameFlow](https://github.com/tobiashaas/LR-FrameFlow)

## Architecture

```text
Lightroom plugin (Lua) ─┐
                        ├→ Bridge (Rust, 127.0.0.1) → API (FastAPI, 202) → Redis queues → workers
lrff-folder (CLI) ──────┘   previews from the RAW,                          feature · train ·
                            SQLite outbox, retries                           inference · cull
                                                       Postgres (+ pgvector) · S3-compatible storage
```

The plugin is only UI; the Bridge builds previews from the original files and talks to the server.
Decisions are recorded in [`docs/adr/`](docs/adr/) (queue, Bridge, culling).

## Repository layout

```text
apps/
  lr-plugin/        # Lightroom Classic plugin (Lua 5.1), German/English UI
  bridge/           # Rust: core (local API, outbox, previews, XMP, lrff-folder) + Tauri shell
packages/
  contracts/        # OpenAPI + JSON Schema — source of truth, validated in CI
services/
  api/              # FastAPI gateway: photos, profiles, train / edit / cull jobs
  workers/          # feature_worker, train_worker, inference_worker, cull_worker
libs/
  domain/ persistence/ queue/ observability/
  inference-pipeline/  # features, models, straighten
  edit-serializer/     # internal parameters ↔ Lightroom develop settings, style layer
  culling/             # sharpness, faces, expressions, series, people, learned scorer
infra/
  compose/          # Postgres + pgvector, Redis, RustFS (S3)
  migrations/       # Alembic migrations
tools/
  lrff_eval/        # offline benchmarks (hold-out, culling against real decisions, straighten)
  lr_e2e/           # end-to-end tests in a real, running Lightroom (automation channel)
```

## Getting started

```bash
# infrastructure
cp infra/compose/env.example infra/compose/.env
cd infra/compose && docker compose -p lrframeflow up -d && cd ../..

# Python (one venv for all components)
python -m venv .venv && .venv\Scripts\activate          # Windows
pip install -e libs/domain -e libs/queue -e libs/persistence -e libs/observability
pip install -e libs/inference-pipeline -e libs/edit-serializer -e libs/culling
pip install -e services/api -e services/workers/feature_worker -e services/workers/train_worker \
            -e services/workers/inference_worker -e services/workers/cull_worker
cd infra/migrations && alembic upgrade head && cd ../..

# API and workers (each in its own terminal)
uvicorn lr_frameflow_api.main:app --host 127.0.0.1 --port 8080
lr-ff-feature-worker; lr-ff-train-worker; lr-ff-inference-worker; lr-ff-cull-worker

# Bridge (Rust)
cd apps/bridge && cargo run --release -p lrff-bridge-core --bin lrff-bridge-headless
```

Then add `apps/lr-plugin/LRFrameFlow.lrplugin` in Lightroom's Plug-in Manager. Details:
[`CLAUDE.md`](CLAUDE.md) (developer overview), [`apps/lr-plugin/README.md`](apps/lr-plugin/README.md),
[`apps/bridge/README.md`](apps/bridge/README.md).

## Tests

All of these run in CI (`.github/workflows/ci.yml`):

```bash
python scripts/validate_contracts.py
pytest libs services                                  # Python libs, API, workers
cd apps/bridge && cargo test -p lrff-bridge-core      # Bridge, incl. end-to-end against a fake API
luajit apps/lr-plugin/tests/run.lua                   # plugin with a faked Lightroom SDK
```

With a running Lightroom and `"automation": true` in `bridge.json`, `tools/lr_e2e/` drives the real
plugin: apply + restore (`run.py`, `--train N`), straighten (`straighten_check.py`), culling
(`cull_check.py`). Every test restores what it changed.

## Models and data

Only permissively licensed models (MIT / Apache-2.0 / BSD, code *and* weights) are used; every one
is listed with source, license and SHA-256 in [`THIRD_PARTY_MODELS.md`](THIRD_PARTY_MODELS.md) and
downloaded on first use. No models, presets or values from other products are part of this project.
Benchmarks against other tools' outputs are internal yardsticks only and never ship.

## License

To be decided (see `LICENSE` once added).
