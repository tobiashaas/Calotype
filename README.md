# Calotype

**An open darkroom that learns your style.**

Calotype edits and culls your photos the way *you* would: it learns your style from photos you
have already edited and your taste from photos you have already rated — and it runs on your own
machine, no cloud, no per-photo fee. It works inside **Lightroom Classic** and on plain RAW + XMP
folders.

> The calotype (Talbot, 1841) was the first negative–positive process: from one negative, any
> number of beautiful prints. Calotype learns your style once and prints it on every photo.

- **Website:** [calotype.xyz](https://calotype.xyz) · **Code:** [github.com/tobiashaas/Calotype](https://github.com/tobiashaas/Calotype)

## What it does

| | |
|---|---|
| **Edit profiles** | Train a profile from finished edits; apply it to new photos. Exposure, white balance and tone are predicted per photo, a fixed look (curve, HSL, color grading …) goes on top. |
| **Culling** | Sorts a shoot into *Keep / Check / Sort out* with a reason per photo ("best of its series", "eyes closed" …). Learns from the stars and flags you already gave, otherwise explainable starter rules. Results are collections — your stars, flags and edits are never changed. |
| **Retouch** | Adds Lightroom's own AI masks (subject, background, skin, eyes, teeth, sky) with gentle adjustments. Masks that find nothing are removed, your own masks stay, the original is kept as a snapshot. |
| **Straighten** | Levels photos with clear reference lines (walls, door frames, horizon) with the largest crop, like Lightroom does. Photos you cropped yourself keep their crop. |
| **Looks** | Eight own looks as Lightroom / Camera Raw presets (CC0), alone or as a profile's style. Installed automatically. |
| **Folder mode** | All of it without Lightroom on RAW + XMP folders: `calotype-folder train / apply / cull`, optionally into a separate output folder so the source stays untouched. |

The Lightroom plugin speaks German and English.

## How it works

```text
Lightroom plugin (Lua) ──┐
                         ├─→ Bridge (Rust, 127.0.0.1) ─→ API (FastAPI) ─→ Redis queues ─→ workers
calotype-folder (CLI) ───┘   previews from the RAW,                                  feature · train
                             SQLite outbox, retries                                  inference · cull
                                                     Postgres + pgvector · S3-compatible storage
```

The plugin is only the user interface. The Bridge builds previews from the original RAW files
(reading just the embedded preview where possible), keeps a local outbox and talks to the server.
The server can run on the same machine or elsewhere. Decisions are recorded in
[`docs/adr/`](docs/adr/).

## Repository layout

```text
apps/
  lr-plugin/          Lightroom Classic plugin (Lua 5.1), German / English
  bridge/             Rust: core (local API, outbox, previews, XMP, calotype-folder, presets) + Tauri app
packages/
  contracts/          OpenAPI + JSON Schema — the source of truth, validated in CI
services/
  api/                FastAPI gateway: photos, profiles, train / edit / cull jobs
  workers/            feature_worker, train_worker, inference_worker, cull_worker
libs/
  domain/  persistence/  queue/  observability/  io/
  inference-pipeline/ features, models, straighten
  edit-serializer/    internal parameters ↔ Lightroom develop settings, style layer
  culling/            sharpness, faces, expressions, series, people, learned scorer
presets/              the project's looks and retouch presets (generated, CC0)
infra/
  compose/            Postgres + pgvector, Redis, RustFS (S3)
  migrations/         Alembic migrations
tools/
  eval/               offline benchmarks: hold-out, culling against real decisions, straighten
  lr_e2e/             end-to-end tests in a real, running Lightroom
  presets/            generator for presets/
```

## Getting started

```bash
# infrastructure
cp infra/compose/env.example infra/compose/.env
cd infra/compose && docker compose -p calotype up -d && cd ../..

# Python (one venv for all components)
python -m venv .venv && .venv\Scripts\activate          # Windows
pip install -e libs/domain -e libs/queue -e libs/persistence -e libs/observability
pip install -e libs/inference-pipeline -e libs/edit-serializer -e libs/culling -e libs/io
pip install -e services/api -e services/workers/feature_worker -e services/workers/train_worker \
            -e services/workers/inference_worker -e services/workers/cull_worker
cd infra/migrations && alembic upgrade head && cd ../..

# API and workers (each in its own terminal)
uvicorn calotype_api.main:app --host 127.0.0.1 --port 8080
calotype-feature-worker   # likewise: calotype-train-worker, calotype-inference-worker, calotype-cull-worker

# Bridge (Rust) — installs the presets for Lightroom on start
cd apps/bridge && cargo run --release -p calotype-bridge-core --bin calotype-bridge-headless
```

Then add `apps/lr-plugin/Calotype.lrplugin` in Lightroom's Plug-in Manager and restart Lightroom.
More: [`apps/lr-plugin/README.md`](apps/lr-plugin/README.md), [`apps/bridge/README.md`](apps/bridge/README.md),
[`presets/README.md`](presets/README.md), developer overview in [`CLAUDE.md`](CLAUDE.md).

## Tests

All of these run in CI (`.github/workflows/ci.yml`):

```bash
python scripts/validate_contracts.py
pytest libs services                                  # Python libs, API, workers
cd apps/bridge && cargo test -p calotype-bridge-core  # Bridge, incl. end-to-end against a fake API
luajit apps/lr-plugin/tests/run.lua                   # plugin with a faked Lightroom SDK
```

With Lightroom running and `"automation": true` in the Bridge's `bridge.json`, `tools/lr_e2e/`
drives the real plugin: apply + restore and training (`run.py`), straighten
(`straighten_check.py`), culling (`cull_check.py`), retouch (`retouch_check.py`). Every test
restores what it changed.

## Status

Working end to end and tested in Lightroom Classic 15.6: profiles, culling, retouch, straighten,
looks, folder mode. Next: culling profiles learned from earlier shoots, retouch strength learned
from your own masks, white balance relative to the camera's as-shot value, support for other raw
converters (RawTherapee, darktable, Capture One). Details in [`TODO.md`](TODO.md).

## Models and data

Only permissively licensed models (MIT / Apache-2.0 / BSD, code *and* weights) are used; each is
listed with source, license and SHA-256 in [`THIRD_PARTY_MODELS.md`](THIRD_PARTY_MODELS.md) and
downloaded on first use. No models, presets or values from other products are part of this
project. Benchmarks against other tools' outputs are internal yardsticks only and never ship.

The retouch approach (mask presets + Lightroom's `updateAISettings`) follows
[Retoucan](https://github.com/joemalott/retoucan) (MIT) — thanks.

## License

To be decided (see `LICENSE` once added). The looks and retouch presets in `presets/` are CC0.
