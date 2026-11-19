"""Benchmark TruFor on the tampering benchmark (same samples as bench_manip) incl. localization F1 vs masks.
Usage: python -m eval.bench_trufor [N]"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.analyzers import trufor
from .metrics import ece, summarize
from .sources import tampered

OUT = Path(__file__).resolve().parent / "results"


def main(n: int = 600):
    data = tampered(n)
    ys, ps, groups, f1s, ious = [], [], [], [], []
    t0 = time.time()
    for k, r in enumerate(data):
        im = Image.open(io.BytesIO(r["bytes"])).convert("RGB")
        out = trufor.analyze(im)
        if out is None:
            print("TruFor unavailable:", trufor.error()); return
        ys.append(r["label"]); ps.append(out["score"]); groups.append(r["group"].split(":")[0])
        if r["label"] == 1 and r.get("mask"):
            gt = np.asarray(Image.open(io.BytesIO(r["mask"])).convert("L").resize(out["map"].shape[::-1], Image.NEAREST)) > 127
            pr = out["map"] > 0.5
            tp = (gt & pr).sum(); fp = (~gt & pr).sum(); fn = (gt & ~pr).sum()
            f1s.append(2 * tp / max(1, 2 * tp + fp + fn)); ious.append(tp / max(1, tp + fp + fn))
        if k % 100 == 0:
            print(f"  {k}/{len(data)} {time.time() - t0:.0f}s", flush=True)
    ys, ps = np.array(ys), np.array(ps)
    s = summarize(ys, ps); s["ece"] = ece(ys, ps)
    s["loc_f1_mean"] = float(np.mean(f1s)) if f1s else None
    s["loc_iou_mean"] = float(np.mean(ious)) if ious else None
    s["sec_per_img"] = (time.time() - t0) / len(ys)
    by = {}
    for g in sorted(set(groups)):
        m = np.array([x == g for x in groups])
        if len(set(ys[m])) == 2:
            by[g] = summarize(ys[m], ps[m])
    print(f"[TruFor] AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f} TPR={s['tpr@0.5']:.2f} TNR={s['tnr@0.5']:.2f} "
          f"ECE={s['ece']:.3f} locF1={s['loc_f1_mean']:.3f} IoU={s['loc_iou_mean']:.3f} {s['sec_per_img']:.2f}s/img", flush=True)
    for g, v in by.items():
        print(f"    {g:16s} n={v['n']:4d} AUC={v['auc']:.3f} acc={v['acc@0.5']:.3f}", flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "trufor_summary.json").write_text(json.dumps({"overall": s, "by_dataset": by}, indent=2))
    np.save(OUT / "trufor_scores.npy", np.stack([ys, ps]))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 600)
