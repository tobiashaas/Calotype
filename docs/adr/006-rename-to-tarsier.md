# ADR 006 — The project is called Tarsier

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Maintainer

## Context

"LR-FrameFlow" no longer fits: the project works without Lightroom (folder mode) and should
support other raw converters later, "LR" is Adobe's mark, and the name says nothing to
photographers. Candidates were checked on GitHub, the web and in TMview (all EU and many
international trademark offices).

## Decision

**Tarsier** — *an open darkroom that learns your style.* The tarsier sees in the dark (the
darkroom) and has huge eyes (looking at photos). Used with a photo context (`tarsier.photo`,
"Tarsier photo") so it is not confused with unrelated AI projects of the same name.

Trademark check (2026-11-08, not legal advice): no TARSIER mark for software or photography in the
EU or Germany (EU: pharma, class 5; an expired clothing mark). UK/US: QinetiQ's runway debris radar
(classes 9/42) — a different market. Some class-9 marks in Korea, China, Türkiye without a photo
context.

### Every name changes at once

| What | Old | New |
|---|---|---|
| Product, UI, docs | LR-FrameFlow | Tarsier |
| Python packages (import) | `lr_frameflow_*`, `lr_edit_serializer`, `lr_io` | `tarsier_*`, `tarsier_edit_serializer`, `tarsier_io` |
| Python distributions | `lr-frameflow-*` | `tarsier-*` |
| Worker commands | `lr-ff-<x>-worker` | `tarsier-<x>-worker` |
| Rust crate / binaries | `lrff-bridge-core`, `lrff-bridge-headless`, `lrff-folder` | `tarsier-bridge-core`, `tarsier-bridge-headless`, `tarsier-folder` |
| Lightroom plugin | `LRFrameFlow.lrplugin`, `io.github.lrframeflow`, `$$$/LRFrameFlow/…` | `Tarsier.lrplugin`, `photo.tarsier.lightroom`, `$$$/Tarsier/…` |
| Bridge data folder, log | `%APPDATA%\LRFrameFlow`, `LRFrameFlow.log` | `%APPDATA%\Tarsier`, `Tarsier.log` |
| Model cache | `%LOCALAPPDATA%\LRFrameFlow\models` | `%LOCALAPPDATA%\Tarsier\models` |
| Environment variables | `LRFF_*` | `TARSIER_*` |
| Bridge token header | `X-LRFF-Token` | `X-Tarsier-Token` |
| XMP namespace | `lrff:` = `https://github.com/tobiashaas/LR-FrameFlow/ns/1.0/` | `tarsier:` = `https://tarsier.photo/ns/1.0/` |
| Redis queues | `lrff:jobs:*` | `tarsier:jobs:*` |
| Defaults: database, S3 bucket, compose project | `lrframeflow`, `lrff-photos` | `tarsier`, `tarsier-photos` |
| Lightroom: collections, preset groups, masks, snapshot | `LR-FrameFlow …` | `Tarsier …` |
| Evaluation tools | `tools/lrff_eval` | `tools/eval` |
| Contract `$id`s | `https://schemas.lr-frameflow/…` | `https://schemas.tarsier.photo/…` |
| GitHub | `tobiashaas/LR-FrameFlow` | `tobiashaas/tarsier` (renamed by the maintainer; GitHub redirects the old URL) |

Schema versions (`bridge-edit-v1`, `edit-request-v1`, …) do not change: they describe the
format, not the product.

### Existing installations keep working

- **Bridge:** on start, an existing `LRFrameFlow` data folder is moved to `Tarsier` (token, queue,
  settings kept); `LRFF_BRIDGE_DATA_DIR` is still read when `TARSIER_BRIDGE_DATA_DIR` is unset; the
  old token header is still accepted.
- **Models:** an existing `LRFrameFlow\models` cache is moved to `Tarsier\models` (no new download).
- **Presets:** the Bridge installs into `Camera Raw\Settings\Tarsier` and removes the files it once
  installed into `…\LR-FrameFlow` (only those files).
- **Retouch:** masks named `LR-FrameFlow <id>` count as ours, so a re-apply replaces them.
- **XMP:** sidecars written with `lrff:` keep their attributes; new writes use `tarsier:`.
- **Lightroom:** the plugin has a new folder and identifier — remove the old plugin and add
  `apps/lr-plugin/Tarsier.lrplugin` once in the Plug-in Manager.
- **Local servers:** existing databases, buckets and compose volumes keep their names; point
  `DATABASE_URL` / `S3_BUCKET` at them (env) or migrate when convenient. In-flight Redis jobs of the
  old queues are not carried over (restart the jobs).

## Consequences

One large, mechanical change; all tests and the Lightroom end-to-end tests run afterwards. The
history of earlier ADRs keeps the old name where it describes the past.
