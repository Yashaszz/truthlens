"""Robustness to metadata stripping and anti-forensic 'laundering'.
Applies common ways people hide traces (strip metadata, recompress, resize, screenshot, blur, noise, crop) to held-out
real and AI images, then measures the calibrated AI-image ensemble on each version.
Usage: python -m eval.bench_robustness [N_PER_SET]"""
from __future__ import annotations

import hashlib
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
    b = io.BytesIO(); im.save(b, "JPEG", quality=q); b.seek(0)
    return Image.open(b).convert("RGB")


ATTACKS = {
    "original": lambda im: im,
    "metadata stripped": lambda im: Image.frombytes("RGB", im.size, im.tobytes()),  # pixels only, no EXIF/XMP/C2PA
    "WhatsApp-style (1600px, JPEG 75)": lambda im: jpeg(im.resize((1600, int(im.height * 1600 / im.width))) if im.width > 1600 else im, 75),
    "heavy JPEG (q=50)": lambda im: jpeg(im, 50),
    "downscaled 50%": lambda im: im.resize((max(64, im.width // 2), max(64, im.height // 2)), Image.BICUBIC),
    "screenshot (crop + PNG)": lambda im: im.crop((int(im.width * .05), int(im.height * .05), int(im.width * .95), int(im.height * .95))),
    "blur (radius 1.5)": lambda im: im.filter(ImageFilter.GaussianBlur(1.5)),
    "added noise (σ=6)": lambda im: Image.fromarray(np.clip(np.asarray(im, np.float32) + np.random.default_rng(0).normal(0, 6, (im.height, im.width, 3)), 0, 255).astype(np.uint8)),
    "all combined": lambda im: jpeg(im.crop((int(im.width * .05), int(im.height * .05), int(im.width * .95), int(im.height * .95)))
                                   .resize((max(64, int(im.width * .6)), max(64, int(im.height * .6))), Image.BICUBIC), 70),
}


def main(n: int = 150):
    used = {hashlib.md5(r["bytes"]).hexdigest() for fn in (tinygen, cfeval) for r in fn(400, 0)}
    data = [r for fn in (tinygen, cfeval) for r in fn(n * 3, seed=11) if hashlib.md5(r["bytes"]).hexdigest() not in used]
    rng = np.random.default_rng(1)
    data = [data[i] for i in rng.permutation(len(data))[: 2 * n]]
    ims = [Image.open(io.BytesIO(r["bytes"])).convert("RGB") for r in data]
    y = np.array([r["label"] for r in data])
    print(f"[data] {len(y)} held-out images ({y.sum()} AI, {len(y) - y.sum()} real)", flush=True)
    out = {}
    for name, f in ATTACKS.items():
        p = detectors.AI_IMAGE.predict([f(im) for im in ims])["p"]
        s = summarize(y, p)
        pv = p >= 0.6  # same cut-off the verdict uses
        out[name] = {"auc": s["auc"], "accuracy": float((pv == y).mean()), "fakes_caught": float(pv[y == 1].mean()),
                     "false_alarms": float(pv[y == 0].mean())}
        o = out[name]
        print(f"  {name:34s} acc={o['accuracy']:.3f}  caught={o['fakes_caught']:.2f}  false-alarms={o['false_alarms']:.2f}  AUC={o['auc']:.3f}", flush=True)
    RES.mkdir(exist_ok=True)
    (RES / "robustness_summary.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
