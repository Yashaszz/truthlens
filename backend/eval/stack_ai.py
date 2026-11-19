"""Build a calibrated AI-image ensemble from benchmark scores.
Evaluates leave-one-dataset-out (train on the other public sets, test on the held-out one) so reported
accuracy reflects generalization to unseen data, then fits on all public sets and writes app/calib/ai_image.json.
Usage: python -m eval.stack_ai"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .metrics import ece, summarize

RES = Path(__file__).resolve().parent / "results"
CALIB = Path(__file__).resolve().parents[1] / "app" / "calib"
PUBLIC = ["GenImage", "CommunityForensics", "WebArt"]
EXCLUDE = {"dima806 ViT"}  # trained on the WebArt source dataset (leakage): excluded from the ensemble
CANDIDATES = ["CommunityForensics ViT", "Smogy Swin", "haywoodsloan SwinV2", "Organika SDXL", "umm-maybe (current)"]


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def load():
    df = pd.read_csv(RES / "ai_images_scores.csv")
    df["i"] = df.groupby(["model", "set"]).cumcount()
    wide = df.pivot_table(index=["set", "i"], columns="model", values="p").reset_index()
    lab = df[df["model"] == df["model"].iloc[0]][["set", "i", "label", "group"]]
    return wide.merge(lab, on=["set", "i"])


def lodo(wide, models, C=1.0):
    ys, ps, per = [], [], {}
    for held in PUBLIC:
        tr = wide[wide["set"].isin([s for s in PUBLIC if s != held])]
        te = wide[wide["set"] == held]
        clf = LogisticRegression(C=C, max_iter=2000).fit(logit(tr[models].values), tr["label"].values)
        p = clf.predict_proba(logit(te[models].values))[:, 1]
        per[held] = summarize(te["label"].values, p)
        ys.append(te["label"].values); ps.append(p)
    y, p = np.concatenate(ys), np.concatenate(ps)
    s = summarize(y, p); s["ece"] = ece(y, p)
    return s, per


def main():
    wide = load()
    results = []
    models_ok = [m for m in CANDIDATES if m in wide.columns]
    for k in (1, 2, 3, 4):
        for combo in combinations(models_ok, k):
            if "CommunityForensics ViT" not in combo and k > 1:
                continue
            s, per = lodo(wide, list(combo))
            results.append((s["auc"], s["acc@0.5"], combo, s, per))
    results.sort(key=lambda r: (-r[1], -r[0]))
    print("Leave-one-dataset-out (calibrated) — top combinations:")
    for auc, acc, combo, s, per in results[:8]:
        print(f"  acc={acc:.3f} AUC={auc:.3f} ECE={s['ece']:.3f}  {' + '.join(combo)}   "
              + "  ".join(f"{k}:{v['acc@0.5']:.2f}" for k, v in per.items()))
    best = results[0]
    combo = list(best[2])
    pub = wide[wide["set"].isin(PUBLIC)]
    clf = LogisticRegression(C=1.0, max_iter=2000).fit(logit(pub[combo].values), pub["label"].values)
    field = wide[wide["set"] == "Field"]
    if len(field):
        pf = clf.predict_proba(logit(field[combo].values))[:, 1]
        print("Field (your uploads):", [(g, int(l), round(float(x), 3)) for g, l, x in zip(field["group"], field["label"], pf)])
    single = [r for r in results if r[2] == ("CommunityForensics ViT",)][0]
    CALIB.mkdir(exist_ok=True)
    (CALIB / "ai_image.json").write_text(json.dumps({
        "models": combo, "coef": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0]),
        "lodo": best[3], "lodo_per_set": best[4], "single_best_lodo": single[3],
        "trained_on": PUBLIC, "n": int(len(pub)),
    }, indent=2))
    print("saved", combo, "coef", np.round(clf.coef_[0], 2), "intercept", round(float(clf.intercept_[0]), 2))


if __name__ == "__main__":
    main()
