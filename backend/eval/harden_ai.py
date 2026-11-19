"""Harden the AI-image ensemble against laundering: refit the calibrated stack on original + laundered copies
(with image-quality features), check leave-one-dataset-out, then compare old vs new on the held-out robustness set.
Usage: python -m eval.harden_ai"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app import detectors
from .bench_robustness import ATTACKS
from .metrics import ece, summarize
from .sources import cfeval, tinygen, webart

CALIB = Path(__file__).resolve().parents[1] / "app" / "calib"
RES = Path(__file__).resolve().parent / "results"
MODELS = ["CommunityForensics ViT", "haywoodsloan SwinV2", "umm-maybe (current)"]
TRAIN_ATTACKS = [k for k in ATTACKS if k not in ("original",)]


def parts_for(images):
    return {m: detectors.get(m).predict(images) for m in MODELS}


def build(rows, rng, copies=2):
    ims, y, src = [], [], []
    for r in rows:
        im = Image.open(io.BytesIO(r["bytes"])).convert("RGB")
        ims.append(im); y.append(r["label"]); src.append(r["src"])
        for a in rng.choice(TRAIN_ATTACKS, size=copies, replace=False):
            ims.append(ATTACKS[a](im)); y.append(r["label"]); src.append(r["src"])
    return ims, np.array(y), np.array(src)


def fit(X, y):
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=0.5, max_iter=3000).fit(sc.transform(X), y)
    return sc, lr


def main():
    rng = np.random.default_rng(5)
    pool = tinygen(400, 0) + cfeval(400, 0) + webart(400, 0)
    ims, y, src = build(pool, rng)
    print(f"[train] {len(y)} images (originals + 2 laundered copies each)", flush=True)
    P = parts_for(ims)
    X = detectors.stack_features(P, MODELS, ims, True)

    lodo = {}
    for held in ("GenImage", "CommunityForensics", "WebArt"):
        tr, te = src != held, src == held
        sc, lr = fit(X[tr], y[tr])
        p = lr.predict_proba(sc.transform(X[te]))[:, 1]
        lodo[held] = summarize(y[te], p)
        print(f"  LODO {held:18s} acc={lodo[held]['acc@0.5']:.3f} AUC={lodo[held]['auc']:.3f}  (originals+laundered)", flush=True)

    sc, lr = fit(X, y)
    old = json.loads((CALIB / "ai_image.json").read_text())
    shutil.copy(CALIB / "ai_image.json", CALIB / "ai_image_v1.json")

    # held-out robustness set (disjoint from calibration pool by hash)
    used = {hashlib.md5(r["bytes"]).hexdigest() for r in pool}
    data = [r for fn in (tinygen, cfeval) for r in fn(450, seed=11) if hashlib.md5(r["bytes"]).hexdigest() not in used]
    data = [data[i] for i in np.random.default_rng(1).permutation(len(data))[:300]]
    base = [Image.open(io.BytesIO(r["bytes"])).convert("RGB") for r in data]
    yt = np.array([r["label"] for r in data])
    table = {}
    print(f"[held-out] {len(yt)} images ({yt.sum()} AI)  —  OLD → NEW  (verdict cut-off 0.6)", flush=True)
    for name, f in ATTACKS.items():
        att = [f(im) for im in base]
        pp = parts_for(att)
        zo = sum(c * detectors.logit(pp[m]) for m, c in zip(old["models"], old["coef"])) + old["intercept"]
        po = 1 / (1 + np.exp(-zo))
        pn = lr.predict_proba(sc.transform(detectors.stack_features(pp, MODELS, att, True)))[:, 1]
        row = {}
        for tag, p in (("old", po), ("new", pn)):
            pv = p >= 0.6
            row[tag] = {"accuracy": float((pv == yt).mean()), "caught": float(pv[yt == 1].mean()), "false_alarms": float(pv[yt == 0].mean())}
        table[name] = row
        o, n = row["old"], row["new"]
        print(f"  {name:34s} acc {o['accuracy']:.3f}→{n['accuracy']:.3f}  caught {o['caught']:.2f}→{n['caught']:.2f}  "
              f"false-alarms {o['false_alarms']:.2f}→{n['false_alarms']:.2f}", flush=True)

    allp = lr.predict_proba(sc.transform(X))[:, 1]
    (CALIB / "ai_image.json").write_text(json.dumps({
        "models": MODELS, "quality": True, "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
        "coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0]),
        "lodo": summarize(y, allp) | {"note": "in-sample summary; see lodo_per_set for held-out"},
        "lodo_per_set": lodo, "single_best_lodo": old.get("single_best_lodo"),
        "robustness": table, "trained_on": ["GenImage", "CommunityForensics", "WebArt"] , "laundering": TRAIN_ATTACKS,
        "previous": "ai_image_v1.json"}, indent=2))
    RES.mkdir(exist_ok=True)
    (RES / "robustness_summary.json").write_text(json.dumps(table, indent=2))
    print("saved hardened calibration", flush=True)


if __name__ == "__main__":
    main()
