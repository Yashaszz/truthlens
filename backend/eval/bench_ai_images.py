"""Benchmark AI-generated-image detectors on labelled public data + field samples.
Usage: python -m eval.bench_ai_images [N_PER_SET]"""
from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .image_models import AI_IMAGE_CANDIDATES, timed_predict
from .metrics import summarize
from .sources import IMAGE_AI_SETS

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)


def main(n: int = 400):
    t0 = time.time()
    sets = {}
    for name, fn in IMAGE_AI_SETS.items():
        sets[name] = fn(n)
        print(f"[data] {name}: {len(sets[name])} samples ({sum(r['label'] for r in sets[name])} fake)", flush=True)
    rows = []
    for mname, make in AI_IMAGE_CANDIDATES.items():
        try:
            det = make()
        except Exception as e:
            print(f"[skip] {mname}: {type(e).__name__}: {e}", flush=True)
            continue
        for sname, data in sets.items():
            p, per = timed_predict(det, [r["bytes"] for r in data])
            for r, pi in zip(data, p):
                rows.append({"model": mname, "set": sname, "group": r["group"], "label": r["label"], "p": float(pi), "sec": per})
            s = summarize([r["label"] for r in data], p)
            print(f"[{mname:24s}] {sname:18s} AUC={s.get('auc', float('nan')):.3f} acc={s['acc@0.5']:.3f} "
                  f"TPR={s.get('tpr@0.5', 0):.2f} TNR={s.get('tnr@0.5', 0):.2f} {per * 1000:.0f} ms/img", flush=True)
        del det
        gc.collect()
        torch.cuda.empty_cache()
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "ai_images_scores.csv", index=False)
    summary = {}
    for (m, s), g in df.groupby(["model", "set"]):
        summary.setdefault(m, {})[s] = summarize(g["label"].values, g["p"].values)
    (OUT / "ai_images_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
