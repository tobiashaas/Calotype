# ADR 005 — Culling: many explainable features, weighted by the photographer's taste

- **Status:** Proposed
- **Date:** 2026-11-06
- **Deciders:** Maintainer
- **Builds on:** [ADR 004](004-bridge-localhost-architecture.md) (Bridge, preview from the original)

## Context

Culling = finding the photos worth keeping among the hundreds or thousands from a shoot.
Rigid rules ("blurry = out", "eyes closed = out") fail precisely on the images that
photographers value most: a slightly blurry moment full of emotion, a laugh with
closed eyes. Good tools on the market break the problem into many specialized
assessments and combine them in a simple, explainable model (an architectural insight,
no adoption of third-party models or values).

**Core requirement:** Technical flaws are *features*, not a veto. Whether an emotionally strong,
technically weak image stays is decided by the photographer's learned taste.

## Decision

### 1. Features per image (all from the Bridge preview, ≤ 1200 px)

| Group | Examples |
|---|---|
| Technical | Overall sharpness and sharpness on the main subject, motion blur, exposure/clipping, noise |
| Face (per face, then best/mean/max per image) | Size, sharpness of the eye region, eyes open (eyelid distance from landmarks), gaze direction, head pose |
| Moment & emotion | Facial expression (laughing, crying, surprise), intensity, interaction (hug, kiss, eye contact), candid vs. posed, body posture |
| Content | Image embedding (e.g. CLIP/DINOv2) and text similarities ("candid moment full of joy", "detail shot", "group photo") |
| Burst | Grouping of near-identical images via embeddings + timestamps; features *relative to the burst* (sharpest, most emotional, most open eyes in the burst) |

Combinations such as "laughing with closed eyes" are features of their own, so they are not
penalized as "eyes closed".

### 2. Scoring model: learned from the photographer's decisions

- Small, explainable model (initially logistic regression or gradient boosting) over
  the normalized features; output: probability of "keep".
- **The training data are existing decisions:** stars, pick/reject, color labels,
  exported photos from Lightroom catalogs (the plugin reads them) or `xmp:Rating` from sidecars.
- Separate weights per profile/genre (wedding ≠ business portrait).
- Calibration of the raw features against the photographer's own collection (percentiles), so thresholds
  mean the same across cameras.

### 3. Result: pre-sort, give reasons, show uncertain cases

- Three buckets: **keep**, **reject**, **uncertain** (close to the decision boundary) — the
  photographer mainly looks at "uncertain".
- Every decision comes with a reason from the strongest features, e.g. "keep: strong
  laugh, interaction; slight blur" or "rejected: eyes closed, no expression,
  sharper image from the same burst available".
- Returned to Lightroom as stars/flags/color labels (plugin) or `xmp:Rating`/
  `xmp:Label` (folder mode).

### 4. Measurement (`lrff-eval cull`)

The yardstick is the photographer's decisions, split into a training and a test set:

- Overall agreement (precision/recall for "keep").
- **Rescued exceptions:** share of technically weak (blurry/eyes closed) but kept
  images that the model also keeps — the metric for the core requirement.
- Individual stages: face detection, eyes open/closed, blur against a labeled sample.
- Time per photo, model size.

### 5. Swappable models, repo with free licenses only

- Every stage sits behind an interface (`face_detector`, `landmarks`, `embedding`, …),
  selected via configuration.
- The repo and releases contain only models with an **MIT/Apache-2.0/BSD** license for code *and*
  weights; every model is listed with source and license in `THIRD_PARTY_MODELS.md`.
- Non-commercial or copyleft models (e.g. AGPL) can be plugged in locally,
  but are never shipped. Models or values from other products are not used.
- `lrff-eval` compares models on the photographer's own photos before a default is switched.

## Consequences / trade-offs

- **Positive:** Explainable and correctable; learns personal taste from data that
  photographers already have; individual stages can be swapped and measured independently.
- **Negative / risks:** Many models = more compute time per photo (goal: < 1 s on CPU;
  a 1200 px preview is enough for faces from ~40 px). Emotion/interaction are the hardest
  features; without enough of the photographer's own decisions (< ~500 images) the model stays coarse — in that case
  starter weights per genre, which improve with every correction.
- **Open:** Where do the models run — worker (server) or Bridge (local, ONNX)? Large
  shoots and privacy argue for local; decision after the first runtime measurements.
