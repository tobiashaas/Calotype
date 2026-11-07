# ADR 004 — Bridge as a local service, plugin as the interface

- **Status:** Accepted
- **Date:** 2026-11-06
- **Deciders:** Maintainer
- **Supplements:** [ADR 002](002-bridge-tauri.md) (Tauri stays in place)

## Context

ADR 002 settles on Tauri, but not on how plugin, Bridge and API work together. Two
established patterns on the market (architecture only, no third-party models or code):

- A local **Rust HTTP service on `127.0.0.1`** with SQLite for job/album state, with a
  lean interface in front.
- A **Lightroom plugin as the interface**, which triggers a local process and writes the results
  into the catalog as develop settings.

What matters to us: Lightroom never freezes, nothing is lost when the network drops, and the
model learns from the **unedited** image, not from the finished look.

## Decision

1. **Plugin (Lua) = interface for the photographer.** Choose a profile, start training/edit,
   apply results via `photo:applyDevelopSettings()` (undoable through
   Lightroom's history). The plugin talks **only to the Bridge**, never directly to the API.
2. **Bridge (Tauri, Rust core) = local service.**
   - axum HTTP server on `127.0.0.1` (default port `47600`, configurable).
   - Local access protection: random token on first start; port and token live in
     `bridge.json` in the app data directory, the plugin reads them from there and sends the
     token as a header.
   - **SQLite outbox:** uploads and job requests are stored locally first, then sent to the API with
     retry and backoff (same `Idempotency-Key` per attempt).
     Job status is polled and cached locally; the plugin only asks the Bridge.
   - Tauri window only for status, login/API address and settings.
3. **Model input = unedited image.** The Bridge creates the preview itself from the
   original file (path from the plugin): for RAW the embedded camera JPEG, for JPEG/TIFF the
   file itself, each downscaled (longest side ≤ 1200 px). The current
   develop settings (`photo:getDevelopSettings()`) are sent along as the training target. This way
   input (before) and target (the photographer's decision) match.
4. **ML stays in Python** (workers). Local inference in the Bridge (ONNX) is a later
   option; the contracts stay unchanged for it.

## Consequences / trade-offs

- **Positive:** Lightroom does not block (the plugin only waits on localhost). Works offline
  thanks to the outbox. No Lightroom render needed for the preview, so it is fast and
  independent of the current look.
- **Negative / risks:** The embedded JPEG follows the camera picture style, not Adobe's
  default profile — that is consistent for training, but it must be present for every camera
  (fallback: Lightroom export with reset settings, open). Two processes
  instead of one: the Bridge must be running, otherwise the plugin shows a clear message.
- **Open:** Whether `getDevelopSettings()` really returns
  `IncrementalTemperature`/`IncrementalTint` for JPEG/TIFF will be checked in the first plugin smoke test
  (mapping in `libs/edit-serializer`).
