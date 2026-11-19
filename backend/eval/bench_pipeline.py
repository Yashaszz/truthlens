"""End-to-end benchmark of the FINAL VERDICT (what a judge sees), not individual detectors.
Runs the full image analyzer + threat matrix on held-out real and fake images (excluding every image used to
calibrate the ensembles, matched by hash) and reports false alarms on real photos and catch rate on fakes.
Usage: python -m eval.bench_pipeline [N_PER_SOURCE]"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.analyzers.image import analyze_image
from app.common import AnalysisContext
from app.config import resolve_options
from app.threats import _claim_info, item_matrix
from .sources import CASES, cfeval, deepfakeface, field, tinygen, USER_LABELS

RES = Path(__file__).resolve().parent / "results"
EXTRA_FIELD = {  # more uploads labelled by a human
    "WhatsApp_Image_2026-10-13_at_22.23.58": (0, "real selfie (phone)"),
    "Photo": (0, "real portrait (retouched)"),
}


def md5(b):
    return hashlib.md5(b).hexdigest()


def field_all():
    out = field()
    for key, (label, group) in EXTRA_FIELD.items():
        hits = sorted(CASES.glob(f"*/evidence/E-*_{key}.*"))
        if hits:
            out.append({"bytes": hits[0].read_bytes(), "label": label, "group": group, "src": "Field"})
    return out


def run_one(r, tmp: Path, claim) -> dict:
    im = Image.open(io.BytesIO(r["bytes"]))
    ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(im.format, ".png")
    d = tmp / md5(r["bytes"])[:10]
    (d / "evidence").mkdir(parents=True, exist_ok=True)
    p = d / "evidence" / f"x{ext}"
    p.write_bytes(r["bytes"])
    ctx = AnalysisContext(d, "TL-bench", resolve_options(None))
    ev = {"id": "E-001", "modality": "image", "filename": p.name}
    s = analyze_image(ctx, ev, p)
    for f in ctx.findings:
        f.setdefault("plain", f["title"])
    m = item_matrix(ev, s, ctx.findings, ctx.signals, claim)
    v = m["verdict"]
    shutil.rmtree(d, ignore_errors=True)
    return {"fake_verdict": bool(v.get("fake")), "verdict": v["label"], "conf": v.get("confidence"), "key": v.get("key"),
            "scores": {k: (None if x is None else round(float(x), 3)) for k, x in (s.get("scores") or {}).items() if not k.startswith("_")}}


def main(n: int = 200):
    used = {md5(r["bytes"]) for fn in (tinygen, cfeval) for r in fn(400, 0)} | {md5(r["bytes"]) for r in deepfakeface(300, 0)}
    sets = {
        "GenImage": [r for r in tinygen(n * 3, seed=7) if md5(r["bytes"]) not in used][:n],
        "CommunityForensics": [r for r in cfeval(n * 3, seed=7) if md5(r["bytes"]) not in used][:n],
        "DeepFakeFace": [r for r in deepfakeface(n * 3, seed=7) if md5(r["bytes"]) not in used][:n],
        "Field": field_all(),
    }
    claim = _claim_info("")
    tmp = Path(tempfile.mkdtemp(prefix="tl-bench-"))
    rows = []
    t0 = time.time()
    for sname, data in sets.items():
        print(f"[data] {sname}: {len(data)} ({sum(r['label'] for r in data)} fake)", flush=True)
        for r in data:
            t = time.time()
            try:
                o = run_one(r, tmp, claim)
            except Exception as e:
                print("   error", type(e).__name__, e, flush=True)
                continue
            rows.append({"set": sname, "group": r["group"], "label": r["label"], **o, "sec": time.time() - t})
            if sname == "Field":
                print(f"   field {r['group']:28s} truth={'FAKE' if r['label'] else 'REAL'}  verdict={o['verdict']} {o['conf']}", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    out = {}
    for sname in list(sets) + ["ALL"]:
        rs = [x for x in rows if sname == "ALL" or x["set"] == sname]
        if not rs:
            continue
        y = np.array([x["label"] for x in rs]); pv = np.array([x["fake_verdict"] for x in rs])
        real, fake = y == 0, y == 1
        out[sname] = {"n": int(len(rs)), "accuracy": float((pv == y).mean()),
                      "false_alarm_rate": float(pv[real].mean()) if real.any() else None,
                      "catch_rate": float(pv[fake].mean()) if fake.any() else None,
                      "sec_per_img": float(np.mean([x["sec"] for x in rs]))}
        o = out[sname]
        print(f"[{sname:18s}] n={o['n']:4d} accuracy={o['accuracy']:.3f}  false-alarms on real={o['false_alarm_rate'] if o['false_alarm_rate'] is None else round(o['false_alarm_rate'], 3)}  "
              f"fakes caught={o['catch_rate'] if o['catch_rate'] is None else round(o['catch_rate'], 3)}  {o['sec_per_img']:.2f}s/img", flush=True)
    fa = [x for x in rows if x["label"] == 0 and x["fake_verdict"]]
    from collections import Counter
    print("false alarms by deciding threat:", Counter(x["key"] for x in fa), flush=True)
    print("missed fakes by group:", Counter(x["group"] for x in rows if x["label"] == 1 and not x["fake_verdict"]), flush=True)
    RES.mkdir(exist_ok=True)
    (RES / "pipeline_summary.json").write_text(json.dumps(out, indent=2))
    (RES / "pipeline_rows.json").write_text(json.dumps(rows, indent=1))
    print(f"done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
