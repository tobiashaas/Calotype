# ADR 006 — The project is called Calotype

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Maintainer

## Context

"LR-FrameFlow" no longer fits: the project works without Lightroom (folder mode) and should
support other raw converters later, "LR" is Adobe's mark, and the name says nothing to
photographers. For a few hours on 2026-11-08 the project was called **Tarsier**; the maintainer
then chose a name from photographic history.

## Decision

**Calotype** — *an open darkroom that learns your style.* The calotype (Talbot, 1841) was the
first negative–positive process: from *one* negative, any number of beautiful prints (*kalos* =
beautiful). Calotype learns a style once and prints it on every photo.

Name check (2026-11-08, not legal advice): no CALOTYPE mark in the EU or Germany; in the UK
"ARKOO by Calotype" (classes 9/42) and an expired CALOTYPE mark. There is an iPhone RAW camera
app called Calotype and several photo studios; the maintainer accepts that — "calotype" is the
name of a historic process, and this is an open-source project. Domain: `calotype.xyz`.

### Every name changes at once

| What | LR-FrameFlow (before) | Calotype |
|---|---|---|
| Product, UI, docs | LR-FrameFlow | Calotype |
| Python packages (import) | `lr_frameflow_*`, `lr_edit_serializer`, `lr_io` | `calotype_*`, `calotype_edit_serializer`, `calotype_io` |
| Python distributions | `lr-frameflow-*` | `calotype-*` |
| Worker commands | `lr-ff-<x>-worker` | `calotype-<x>-worker` |
| Rust crate / binaries | `lrff-bridge-core`, `lrff-bridge-headless`, `lrff-folder` | `calotype-bridge-core`, `calotype-bridge-headless`, `calotype-folder` |
| Lightroom plugin | `LRFrameFlow.lrplugin`, `io.github.lrframeflow`, `$$$/LRFrameFlow/…` | `Calotype.lrplugin`, `xyz.calotype.lightroom`, `$$$/Calotype/…` |
| Desktop app id | — | `xyz.calotype.bridge` |
| Bridge data folder, log | `%APPDATA%\LRFrameFlow`, `LRFrameFlow.log` | `%APPDATA%\Calotype`, `Calotype.log` |
| Model cache | `%LOCALAPPDATA%\LRFrameFlow\models` | `%LOCALAPPDATA%\Calotype\models` |
| Environment variables | `LRFF_*` | `CALOTYPE_*` |
| Bridge token header | `X-LRFF-Token` | `X-Calotype-Token` |
| XMP namespace | `lrff:` = `https://github.com/tobiashaas/LR-FrameFlow/ns/1.0/` | `calotype:` = `https://calotype.xyz/ns/1.0/` |
| Redis queues | `lrff:jobs:*` | `calotype:jobs:*` |
| Defaults: database, S3 bucket, compose project | `lrframeflow`, `lrff-photos` | `calotype`, `calotype-photos` |
| Lightroom: collections, preset groups, masks, snapshot | `LR-FrameFlow …` | `Calotype …` |
| Evaluation tools | `tools/lrff_eval` | `tools/eval` |
| Contract `$id`s | `https://schemas.lr-frameflow/…` | `https://schemas.calotype.xyz/…` |
| GitHub | `tobiashaas/LR-FrameFlow` | `tobiashaas/calotype` (renamed by the maintainer; GitHub redirects the old URL) |

The interim Tarsier names (`Tarsier`, `TARSIER_*`, `X-Tarsier-Token`, `tarsier:`) follow the same
pattern. Schema versions (`bridge-edit-v1`, `edit-request-v1`, …) do not change: they describe the
format, not the product.

### Existing installations keep working

- **Bridge:** on start, an existing `LRFrameFlow` or `Tarsier` data folder is moved to `Calotype`
  (token, queue, settings kept); the old `*_BRIDGE_DATA_DIR` variables and token headers are still
  accepted.
- **Models:** an existing `LRFrameFlow\models` or `Tarsier\models` cache is moved (no new download).
- **Presets:** the Bridge installs into `Camera Raw\Settings\Calotype` and removes the files it once
  installed under the old folder names (only those files).
- **Retouch:** masks named `LR-FrameFlow <id>` or `Tarsier <id>` count as ours, so a re-apply
  replaces them.
- **XMP:** `lrff:` / `tarsier:` attributes are upgraded to `calotype:` on the next write.
- **Lightroom:** the plugin has a new folder and identifier — remove the old plugin and add
  `apps/lr-plugin/Calotype.lrplugin` once in the Plug-in Manager.
- **Local servers:** existing databases, buckets and compose volumes keep their names; point
  `DATABASE_URL` / `S3_BUCKET` at them (env) or migrate when convenient. In-flight Redis jobs of the
  old queues are not carried over.

## Consequences

One large, mechanical change; all tests and the Lightroom end-to-end tests run afterwards. Earlier
ADRs use the new names in paths and commands so they stay usable.
