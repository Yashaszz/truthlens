"""Calibrate the classical manipulation detector on real tampering benchmarks (CASIA, Columbia, Coverage, …).
Fits a logistic regression on forensic features with 5-fold cross-validation, reports honest held-out
accuracy, and writes the fitted model to app/calib/manipulation.json for use in production.
Usage: python -m eval.bench_manip [N]"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.analyzers.forensics import MANIP_FEATURES, classical_features
from .metrics import ece, summarize
from .sources import tampered

CALIB = Path(__file__).resolve().parents[1] / "app" / "calib"
OUT = Path(__file__).resolve().parent / "results"


def main(n: int = 600):
    t0 = time.time()
    data = tampered(n)
    print(f"[data] {len(data)} images ({sum(r['label'] for r in data)} tampered); groups: "
          f"{sorted({r['group'].split(':')[0] for r in data})}", flush=True)
    X, y, groups = [], [], []
    for r in data:
        try:
            f = classical_features(Image.open(io.BytesIO(r["bytes"])))
        except Exception:
            continue
        X.append([f[k] for k in MANIP_FEATURES])
        y.append(r["label"])
        groups.append(r["group"])
    X, y = np.array(X), np.array(y)
    print(f"[features] {len(y)} rows in {time.time() - t0:.0f}s", flush=True)
    model = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced"))
    cv = StratifiedKFold(5, shuffle=True, random_state=0)
    p = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
    s = summarize(y, p)
    s["ece"] = ece(y, p)
    by = {}
    for g in sorted({gg.split(":")[0] for gg in groups}):
        m = np.array([gg.split(":")[0] == g for gg in groups])
        if len(set(y[m])) == 2:
            by[g] = summarize(y[m], p[m])
    print(f"[manipulation] 5-fold CV  AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f} TPR={s['tpr@0.5']:.2f} "
          f"TNR={s['tnr@0.5']:.2f} ECE={s['ece']:.3f}", flush=True)
    for g, v in by.items():
        print(f"    {g:14s} n={v['n']:4d} AUC={v['auc']:.3f} acc={v['acc@0.5']:.3f}", flush=True)
    model.fit(X, y)
    sc, lr = model.named_steps["standardscaler"], model.named_steps["logisticregression"]
    CALIB.mkdir(exist_ok=True)
    (CALIB / "manipulation.json").write_text(json.dumps({
        "features": MANIP_FEATURES, "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
        "coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0]),
        "cv": s, "by_dataset": by, "n": int(len(y)), "source": "KhangTruong/Tampered-Images-Combined-Dataset-2",
    }, indent=2))
    OUT.mkdir(exist_ok=True)
    (OUT / "manipulation_summary.json").write_text(json.dumps({"cv": s, "by_dataset": by}, indent=2))
    print("[coef]", {k: round(c, 2) for k, c in zip(MANIP_FEATURES, lr.coef_[0])}, flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 600)
