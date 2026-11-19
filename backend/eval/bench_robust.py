"""Robustness to metadata stripping and trace-laundering (anti-forensics).
Applies common 'laundering' operations to held-out real+fake images and re-scores the shipped AI-image ensemble.
Usage: python -m eval.bench_robust [N_PER_SET]"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from app import detectors
from .metrics import summarize
from .sources import cfeval, tinygen

RES = Path(__file__).resolve().parent / "results"


def jpeg(im, q):
    b = io.BytesIO(); im.save(b, "JPEG", quality=q); b.seek(0); return Image.open(b).convert("RGB")


ATTACKS = {
    "original (metadata stripped)": lambda im: im,  # decoding to pixels drops all EXIF/C2PA/XMP
    "JPEG q70 (WhatsApp-like)": lambda im: jpeg(im, 70),
    "JPEG q50": lambda im: jpeg(im, 50),
    "resize 50%": lambda im: im.resize((max(64, im.width // 2), max(64, im.height // 2)), Image.BICUBIC),
    "blur r=1": lambda im: im.filter(ImageFilter.GaussianBlur(1)),
    "noise σ=5": lambda im: Image.fromarray(np.clip(np.asarray(im, np.float32) + np.random.default_rng(0).normal(0, 5, (im.height, im.width, 3)), 0, 255).astype(np.uint8)),
    "screenshot chain (resize 75% + JPEG q80)": lambda im: jpeg(im.resize((int(im.width * .75), int(im.height * .75)), Image.BILINEAR), 80),
}


def main(n=150):
    data = tinygen(n, seed=11) + cfeval(n, seed=11)
    ims = [Image.open(io.BytesIO(r["bytes"])).convert("RGB") for r in data]
    y = np.array([r["label"] for r in data])
    out = {}
    for name, f in ATTACKS.items():
        p = detectors.AI_IMAGE.predict([f(im) for im in ims])["p"]
        s = summarize(y, p); out[name] = s
        print(f"{name:42s} acc={s['acc@0.5']:.3f} AUC={s['auc']:.3f} caught={s['tpr@0.5']:.2f} real-cleared={s['tnr@0.5']:.2f}", flush=True)
    RES.mkdir(exist_ok=True)
    (RES / "robustness_summary.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
