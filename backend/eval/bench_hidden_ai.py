"""Validate the tile-scan 'hidden AI alteration' score on AI-inpainting benchmarks vs authentic photos.
Usage: python -m eval.bench_hidden_ai"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from app import detectors
from .metrics import summarize
from .sources import tampered

RES = Path(__file__).resolve().parent / "results"
INPAINT = ("CocoGlide", "OpenSDID", "TGIF2")


def scan(im: Image.Image, cf, p_global: float) -> float:
    if max(im.size) > 1536:
        s = 1536 / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.BICUBIC)
    W, H = im.size
    T, S = 384, 288
    if W < T or H < T:
        im = im.resize((max(W, T), max(H, T)), Image.BICUBIC)
        W, H = im.size
    xs = sorted(set(list(range(0, W - T + 1, S)) + [W - T]))
    ys = sorted(set(list(range(0, H - T + 1, S)) + [H - T]))
    tp = cf.predict([im.crop((x, y, x + T, y + T)) for y in ys for x in xs], crop=False)
    top, frac = float(tp.max()), float((tp >= 0.8).mean())
    return top * (1 - p_global) if (top >= 0.8 and frac < 0.6) else top * (1 - p_global) * 0.5


def main():
    data = [r for r in tampered(1200, seed=3) if r["label"] == 0 or r["group"].startswith(INPAINT)]
    cf = detectors.get("CommunityForensics ViT")
    ys, ps, gl, groups = [], [], [], []
    for r in data:
        im = Image.open(io.BytesIO(r["bytes"])).convert("RGB")
        pg = float(detectors.AI_IMAGE.predict([im])["p"][0])
        ys.append(r["label"]); ps.append(scan(im, cf, pg)); gl.append(pg); groups.append(r["group"].split(":")[0])
    ys, ps, gl = np.array(ys), np.array(ps), np.array(gl)
    s = summarize(ys, ps)
    sg = summarize(ys, np.maximum(ps, gl))
    print(f"[hidden-AI tile score] n={len(ys)} ({ys.sum()} inpainted) AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f} "
          f"TPR={s['tpr@0.5']:.2f} FPR={1 - s['tnr@0.5']:.2f}", flush=True)
    print(f"[max(tile, global)]   AUC={sg['auc']:.3f} acc={sg['acc@0.5']:.3f} TPR={sg['tpr@0.5']:.2f} FPR={1 - sg['tnr@0.5']:.2f}", flush=True)
    for g in sorted(set(groups)):
        m = np.array([x == g for x in groups])
        print(f"    {g:18s} n={m.sum():4d} flagged(>=0.5)={np.mean(np.maximum(ps, gl)[m] >= 0.5):.2f}", flush=True)
    RES.mkdir(exist_ok=True)
    (RES / "hidden_ai_summary.json").write_text(json.dumps({"tile": s, "tile_or_global": sg}, indent=2))


if __name__ == "__main__":
    main()
