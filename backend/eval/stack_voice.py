"""Calibrated voice-deepfake ensemble. Cross-dataset evaluation: fit on one public set, test on the other.
Models known to be trained on one of the sets are excluded. Writes app/calib/voice.json.
Usage: python -m eval.stack_voice"""
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
SETS = ["InTheWild", "ElevenLabsSet"]
CANDIDATES = ["mo-thecreator", "Gustking XLSR-large"]
REPO = {"mo-thecreator": "mo-thecreator/Deepfake-audio-detection",
        "Gustking XLSR-large": "Gustking/wav2vec2-large-xlsr-deepfake-audio-classification"}
FAKE = {"mo-thecreator": ["fake"], "Gustking XLSR-large": ["fake"]}


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def main():
    df = pd.read_csv(RES / "all_scores.csv")
    df = df[df["task"] == "audio"].copy()
    df["i"] = df.groupby(["model", "set"]).cumcount()
    wide = df.pivot_table(index=["set", "i"], columns="model", values="p").reset_index()
    lab = df[df["model"] == CANDIDATES[0]][["set", "i", "label"]]
    wide = wide.merge(lab, on=["set", "i"])
    rows = []
    for k in (1, 2):
        for combo in combinations(CANDIDATES, k):
            combo = list(combo)
            ys, ps, per = [], [], {}
            for held in SETS:
                tr, te = wide[wide["set"] != held], wide[wide["set"] == held]
                clf = LogisticRegression(max_iter=2000).fit(logit(tr[combo].values), tr["label"])
                p = clf.predict_proba(logit(te[combo].values))[:, 1]
                per[held] = summarize(te["label"].values, p)
                ys.append(te["label"].values); ps.append(p)
            y, p = np.concatenate(ys), np.concatenate(ps)
            s = summarize(y, p); s["ece"] = ece(y, p)
            rows.append((s, per, combo))
            print(f"  acc={s['acc@0.5']:.3f} AUC={s['auc']:.3f} ECE={s['ece']:.3f}  {' + '.join(combo)}   "
                  + "  ".join(f"{h}:{v['acc@0.5']:.2f}/{v['auc']:.2f}" for h, v in per.items()))
    s, per, combo = max(rows, key=lambda r: (r[0]["auc"], r[0]["acc@0.5"]))
    clf = LogisticRegression(max_iter=2000).fit(logit(wide[combo].values), wide["label"])
    CALIB.mkdir(exist_ok=True)
    (CALIB / "voice.json").write_text(json.dumps({
        "models": combo, "repos": [REPO[m] for m in combo], "fake_labels": [FAKE[m] for m in combo],
        "coef": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0]),
        "cross_dataset": s, "per_set": per, "trained_on": SETS}, indent=2))
    print("saved", combo, np.round(clf.coef_[0], 2), round(float(clf.intercept_[0]), 2))


if __name__ == "__main__":
    main()
