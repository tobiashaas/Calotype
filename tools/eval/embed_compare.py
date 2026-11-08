"""Compare image-embedding models on both tasks (offline experiment, needs torch).

    python tools/eval/embed_compare.py <preview_dir> <work_dir> <cull_features.json> <raw_dir>

For each model: embeddings of all previews (cached per model in <work_dir>), then
- editing: v2 features + PCA-32 of the embedding → gradient boosting (exposure/temperature/tint)
- culling: learned scorer features + PCA-16 of the embedding → logistic regression (ROC-AUC)
Same train/test split as holdout.py. Only permissively licensed checkpoints (THIRD_PARTY_MODELS.md
rules): DINOv2 (Apache-2.0), Meta Perception Encoder (Apache-2.0), SigLIP 2 (Apache-2.0).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import SLIDERS  # noqa: E402

MODELS = {
    "dinov2-s14": "hub:facebookresearch/dinov2:dinov2_vits14",
    "pe-core-s16-384": "timm:vit_pe_core_small_patch16_384.fb",
    "pe-core-b16-224": "timm:vit_pe_core_base_patch16_224.fb",
    "siglip2-b16-224": "hf:google/siglip2-base-patch16-224",
}


def embedder(spec: str):
    import torch

    kind, _, name = spec.partition(":")
    if kind == "hub":
        repo, _, entry = name.partition(":")
        model = torch.hub.load(repo, entry, verbose=False).eval()
        mean, std, size = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 224
        m, s = torch.tensor(mean).view(3, 1, 1), torch.tensor(std).view(3, 1, 1)

        def prep(im):
            x = torch.from_numpy(np.asarray(im.resize((size, size), Image.BICUBIC), np.float32) / 255).permute(2, 0, 1)
            return (x - m) / s

        return prep, lambda b: model(b)
    if kind == "timm":
        import timm

        model = timm.create_model(name, pretrained=True, num_classes=0).eval()
        cfg = timm.data.resolve_data_config({}, model=model)
        tf = timm.data.create_transform(**cfg)
        return tf, lambda b: model(b)
    from transformers import AutoModel, AutoProcessor

    model = AutoModel.from_pretrained(name).eval()
    proc = AutoProcessor.from_pretrained(name)

    def prep(im):
        return proc(images=im, return_tensors="pt")["pixel_values"][0]

    def run(b):
        out = model.get_image_features(pixel_values=b)
        return out.pooler_output if hasattr(out, "pooler_output") else out

    return prep, run


def embed(key: str, preview_dir: Path, names: list[str], work: Path) -> tuple[np.ndarray, float]:
    cache = work / f"emb_{key}.npz"
    if cache.exists():
        z = np.load(cache)
        if list(z["names"]) == names:
            return z["emb"], float(z["ms"])
    import torch

    prep, run = embedder(MODELS[key])
    out, batch, t0 = [], [], time.perf_counter()
    with torch.inference_mode():
        for i, n in enumerate(names):
            batch.append(prep(Image.open(preview_dir / f"{n}.jpg").convert("RGB")))
            if len(batch) == 32 or i == len(names) - 1:
                out.append(run(torch.stack(batch)).float().numpy())
                batch = []
    ms = 1000 * (time.perf_counter() - t0) / len(names)
    emb = np.concatenate(out)
    np.savez(cache, names=np.array(names), emb=emb, ms=ms)
    print(f"  {key}: {emb.shape[1]}-d, {ms:.0f} ms/photo (batched, CPU)")
    return emb, ms


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    preview_dir, work, cull_json, raw_dir = (Path(a) for a in sys.argv[1:5])
    only = sys.argv[5].split(",") if len(sys.argv) > 5 else list(MODELS)

    from sklearn.decomposition import PCA
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from cull_compare import load_or_analyze, ref_bucket, reference
    from calotype_culling.learned import feature_matrix

    z = np.load(work / "model_lab_features.npz")
    Xtr, Xte, Ytr, Yte = z["tr_hist+stats+face"], z["te_hist+stats+face"], z["Ytr"][:, :3], z["Yte"][:, :3]

    def stems(f):
        return [Path(n).stem for n in (work / f).read_text(encoding="utf-8").split() if n]

    tr = [n for n in stems("train.txt") if (preview_dir / f"{n}.jpg").exists()]
    te = [n for n in stems("test.txt") if (preview_dir / f"{n}.jpg").exists()]

    feats = load_or_analyze([], cull_json)
    by_name = {Path(f.name).stem: i for i, f in enumerate(feats)}
    C = feature_matrix(feats)
    keep = np.array([ref_bucket(*reference(raw_dir, Path(f.name).stem)) == "keep" for f in feats])
    ctr = np.array([by_name[n] for n in tr])
    cte = np.array([by_name[n] for n in te])

    tol = np.array([SLIDERS[k][0] for k in ("Exposure2012", "Temperature", "Tint")])

    def edit_score(A, B):
        pred = np.column_stack([HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05,
                                                              l2_regularization=1.0, random_state=0)
                                .fit(A, Ytr[:, j]).predict(B) for j in range(3)])
        err = np.abs(pred - Yte)
        return err[:, 0].mean(), err[:, 1].mean(), (err <= tol).all(axis=1).mean()

    def cull_auc(A, B):
        s = StandardScaler().fit(A)
        m = LogisticRegression(max_iter=3000, class_weight="balanced").fit(s.transform(A), keep[ctr])
        return roc_auc_score(keep[cte], m.predict_proba(s.transform(B))[:, 1])

    print(f"{'embedding':<18}{'ms/photo':>9}{'exp MAE':>9}{'temp MAE':>10}{'all-3 ok':>10}{'cull AUC':>10}")
    e = edit_score(Xtr, Xte)
    print(f"{'(none, v2 only)':<18}{'':>9}{e[0]:>9.3f}{e[1]:>10.1f}{e[2]:>10.0%}{cull_auc(C[ctr], C[cte]):>10.3f}")
    for key in only:
        emb, ms = embed(key, preview_dir, tr + te, work)
        Etr, Ete = emb[: len(tr)], emb[len(tr):]
        p32 = PCA(32, random_state=0).fit(Etr)
        e = edit_score(np.hstack([Xtr, p32.transform(Etr)]), np.hstack([Xte, p32.transform(Ete)]))
        p16 = PCA(16, random_state=0).fit(Etr)
        auc = cull_auc(np.hstack([C[ctr], p16.transform(Etr)]), np.hstack([C[cte], p16.transform(Ete)]))
        print(f"{key:<18}{ms:>9.0f}{e[0]:>9.3f}{e[1]:>10.1f}{e[2]:>10.0%}{auc:>10.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
