# ADR 002 — Bridge implementation on Tauri (Rust core)

- **Status:** Accepted
- **Date:** 2026-05-01
- **Deciders:** Maintainer

## Context

The Bridge handles file system, network and local reliability tasks between the Lightroom plugin and the backend. Both **Electron** and **Tauri** were options in the original document.

## Decision

Use **Tauri** with a Rust core as the primary choice for:

- smaller artifacts and lower baseline runtime load,
- structured access to native dialogs/OS integration,
- a safer sandboxing concept compared with an always-bundled Chromium shell process.

An **Electron** pivot deliberately remains possible if the team is deep in TypeScript-heavy integration work; all network contracts already live in [`packages/contracts`](../../packages/contracts), so only the local implementation would be swapped.

## Consequences / trade-offs

- **Positive:** Fits a lean plugin + cloud-heavy ML stack without a second "heavy" runtime footprint.
- **Negative:** Web teams need a Rust/TS bridge for the UI; steeper learning curve than classic Electron.
