# Third-party models

Every machine-learning model LR-FrameFlow downloads or ships is listed here. A model is only
added when **both code and weights** are under a permissive license (MIT, Apache-2.0, BSD)
— so the project stays open source and every user, including professional photographers,
may use it commercially ([ADR 005](docs/adr/005-culling-architecture.md)).

Models are **not stored in the repository**. They are downloaded on first use, checked
against the SHA-256 below and cached in `%LOCALAPPDATA%\LRFrameFlow\models`
(`~/.cache/LRFrameFlow/models` elsewhere; override with `LRFF_MODEL_DIR`). The registry in
code: `libs/culling/src/lr_frameflow_culling/models.py`.

| Name | Used for | License (code / weights) | Source | SHA-256 |
|---|---|---|---|---|
| YuNet (`face_detection_yunet_2023mar.onnx`) | Face detection, also small and distant faces | MIT / MIT | [opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| MediaPipe Face Landmarker (`face_landmarker.task`, float16 v1) | Face landmarks + blendshapes (eyes closed, smile, mouth open) | Apache-2.0 / Apache-2.0 | [Google AI Edge](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| SFace (`face_recognition_sface_2021dec.onnx`) | Face embedding: which photos show the same person (culling per person, stays local) | Apache-2.0 / Apache-2.0 (training data: public research face datasets, see the [SFace paper](https://arxiv.org/abs/2205.12010)) | [opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

Libraries with built-in models: OpenCV (Apache-2.0), MediaPipe (Apache-2.0).

## Rules

- Before adding a model, check the license of the **weights**, not just the code; they often
  differ. Non-commercial (e.g. CC BY-NC, many InsightFace models) and copyleft (e.g. AGPL)
  models are not shipped. Users may plug such models in locally at their own responsibility.
- Models or parameters extracted from other products are never used.
- Compare a candidate on your own photos with `tools/lrff_eval` before it becomes a default.
