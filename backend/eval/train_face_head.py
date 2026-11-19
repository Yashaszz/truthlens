"""Train a face-swap head on Community Forensics ViT features.
Train: DeepFakeFace *train* shards. Test: DeepFakeFace *test* shards (disjoint files). Writes app/calib/face_head.npz.
Usage: python -m eval.train_face_head"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.detectors import CommunityForensicsViT, DEV
from .metrics import ece, summarize
from .sources import _dl, _img_bytes, deepfakeface

CALIB = Path(__file__).resolve().parents[1] / "app" / "calib"
RES = Path(__file__).resolve().parent / "results"


@torch.no_grad()
def embed(cf: CommunityForensicsViT, images, bs=32):
    feats, logits = [], []
    for i in range(0, len(images), bs):
        x = torch.stack([cf._prep(Image.open(io.BytesIO(b)).convert("RGB")) for b in images[i:i + bs]]).to(DEV, cf.model.dtype)
        h = cf.model.vit(pixel_values=x).last_hidden_state[:, 0, :].float()
        feats.append(h.cpu().numpy())
        logits.append(cf.model.classifier(h.to(cf.model.dtype)).float().squeeze(-1).cpu().numpy())
    return np.concatenate(feats), np.concatenate(logits)


def train_rows(shards=(3, 25, 50, 75, 100, 125, 150, 175, 200, 214), per_class=900, seed=1):
    rows = []
    for s in shards:
        t = pq.read_table(_dl("juhi-neeved/deepfakeface-labeled", f"data/train-{s:05d}-of-00216.parquet"))
        rows += [{"bytes": _img_bytes(i), "label": int(b), "group": c}
                 for i, b, c in zip(t["image"].to_pylist(), t["binary_label"].to_pylist(), t["class_name"].to_pylist())]
    rnd = np.random.default_rng(seed)
    fake = [r for r in rows if r["label"] == 1]; real = [r for r in rows if r["label"] == 0]
    rnd.shuffle(fake); rnd.shuffle(real)
    return fake[:per_class] + real[:per_class]


def main():
    t0 = time.time()
    cf = CommunityForensicsViT()
    tr = train_rows()
    te = deepfakeface(600)
    print(f"[data] train {len(tr)} ({sum(r['label'] for r in tr)} fake) groups={sorted({r['group'] for r in tr})}; test {len(te)}", flush=True)
    Xtr, Ltr = embed(cf, [r["bytes"] for r in tr]); ytr = np.array([r["label"] for r in tr])
    Xte, Lte = embed(cf, [r["bytes"] for r in te]); yte = np.array([r["label"] for r in te])
    print(f"[embed] {time.time() - t0:.0f}s", flush=True)
    base = summarize(yte, 1 / (1 + np.exp(-Lte)))
    print(f"[baseline CF ViT]   test AUC={base['auc']:.3f} acc={base['acc@0.5']:.3f}", flush=True)
    best = None
    for C in (0.01, 0.03, 0.1, 0.3, 1.0):
        clf = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=4000))
        cvp = cross_val_predict(clf, Xtr, ytr, cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")[:, 1]
        s = summarize(ytr, cvp)
        print(f"  C={C:<5} train-CV AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f}", flush=True)
        if best is None or s["auc"] > best[0]:
            best = (s["auc"], C)
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=best[1], max_iter=4000)).fit(Xtr, ytr)
    p = clf.predict_proba(Xte)[:, 1]
    s = summarize(yte, p); s["ece"] = ece(yte, p)
    groups = [r["group"] for r in te]
    by = {g: {"recall": float((p[np.array(groups) == g] >= 0.5).mean())} for g in sorted(set(groups))}
    print(f"[face head] held-out test AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f} TPR={s['tpr@0.5']:.2f} TNR={s['tnr@0.5']:.2f} ECE={s['ece']:.3f}", flush=True)
    print("   per group (fraction called fake):", {g: round(v["recall"], 2) for g, v in by.items()}, flush=True)
    sc, lr = clf.named_steps["standardscaler"], clf.named_steps["logisticregression"]
    CALIB.mkdir(exist_ok=True)
    np.savez(CALIB / "face_head.npz", mean=sc.mean_, scale=sc.scale_, coef=lr.coef_[0], intercept=lr.intercept_)
    meta = {"backbone": "buildborderless/CommunityForensics-DeepfakeDet-ViT", "C": best[1], "test": s, "baseline_test": base,
            "per_group": by, "train_n": int(len(ytr)), "test_n": int(len(yte)), "source": "juhi-neeved/deepfakeface-labeled"}
    (CALIB / "face_head.json").write_text(json.dumps(meta, indent=2))
    RES.mkdir(exist_ok=True)
    (RES / "face_head_summary.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
