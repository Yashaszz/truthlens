"""Labelled benchmark samples pulled from public HuggingFace datasets (only the shards we need).
Every loader returns a list of dicts: {"bytes": raw file bytes, "label": 1 fake / 0 real, "group": str, "src": str}."""
from __future__ import annotations

import glob
import io
import random
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

import os

ROOT = Path(__file__).resolve().parent
# Keep multi-GB benchmark data out of the project folder (which may be cloud-synced, e.g. OneDrive).
CACHE = Path(os.getenv("TRUTHLENS_EVAL_DATA", Path(os.getenv("LOCALAPPDATA", Path.home() / ".cache")) / "truthlens" / "eval-data"))
CASES = ROOT.parent / "data" / "cases"


def _dl(repo: str, f: str) -> str:
    p = hf_hub_download(repo, f, repo_type="dataset", cache_dir=str(CACHE))
    if os.path.getsize(p) == 0:  # left behind by an interrupted download
        p = hf_hub_download(repo, f, repo_type="dataset", cache_dir=str(CACHE), force_download=True)
    return p


def _balanced(rows: list[dict], n: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    fake = [r for r in rows if r["label"] == 1]
    real = [r for r in rows if r["label"] == 0]
    rnd.shuffle(fake)
    rnd.shuffle(real)
    k = min(n // 2, len(fake), len(real))
    out = fake[:k] + real[:k]
    rnd.shuffle(out)
    return out


def _img_bytes(v):
    if isinstance(v, dict):
        return v.get("bytes")
    return v


def tinygen(n: int = 400, seed: int = 0) -> list[dict]:
    """GenImage (tiny): ImageNet photos vs ADM, BigGAN, GLIDE, Midjourney, SD1.4/1.5, VQDM, Wukong."""
    names = ["Real", "ADM", "BigGAN", "GLIDE", "Midjourney", "SD14", "SD15", "VQDM", "Wukong"]
    t = pq.read_table(_dl("TheKernel01/Tiny-GenImage", "data/validation-00000-of-00004.parquet"))
    rows = [{"bytes": _img_bytes(i), "label": int(l), "group": names[g], "src": "GenImage"}
            for i, l, g in zip(t["image"].to_pylist(), t["label"].to_pylist(), t["generator"].to_pylist())]
    return _balanced(rows, n, seed)


def cfeval(n: int = 400, seed: int = 0, shards=(0, 37, 96, 136, 176, 205, 263, 300, 337, 358)) -> list[dict]:
    # shards chosen among the <90 MB files, spread across the generator-ordered index (some shards are several GB)
    """Community Forensics eval set (CVPR 2025): COCO/FFHQ/etc. photos vs many recent generators."""
    rows = []
    for s in shards:
        t = pq.read_table(_dl("OwensLab/CommunityForensics-Eval", f"data/CompEval-{s:05d}-of-00413.parquet"),
                          columns=["image_data", "label", "model_name"])
        rows += [{"bytes": b, "label": int(l), "group": m, "src": "CommunityForensics"}
                 for b, l, m in zip(t["image_data"].to_pylist(), t["label"].to_pylist(), t["model_name"].to_pylist())]
    return _balanced(rows, n, seed)


def webart(n: int = 400, seed: int = 0) -> list[dict]:
    """AI art scraped from the web vs real photos/art (closest to what people forward on social media)."""
    rows = []
    for f in ("data/train-00001-of-00006-8ad2d550254dea81.parquet", "data/train-00004-of-00006-1101eaf5152e1c5f.parquet",
              "data/train-00000-of-00006-336b26d54a26e17a.parquet"):
        t = pq.read_table(_dl("Hemg/AI-Generated-vs-Real-Images-Datasets", f))
        rows += [{"bytes": _img_bytes(i), "label": 1 if int(l) == 0 else 0, "group": "AiArt" if int(l) == 0 else "Real",
                  "src": "WebArt"} for i, l in zip(t["image"].to_pylist(), t["label"].to_pylist())]
    return _balanced(rows, n, seed)


# Ground truth for the files uploaded during development (judged by a human).
USER_LABELS = {
    "Screenshot_2026-11-19_104948": (1, "AI portrait"),
    "sBe9VWUdei8QAqDv1myo": (1, "AI illustration"),
    "7xm.xyz802943": (0, "press photo"),
    "Virat_Kohli_in_Blue_Jersey": (1, "AI (IPTC-tagged)"),
}


def field(n: int = 0, seed: int = 0) -> list[dict]:
    out = []
    for key, (label, group) in USER_LABELS.items():
        hits = glob.glob(str(CASES / "*" / "evidence" / f"E-*_{key}*"))
        if hits:
            out.append({"bytes": Path(hits[0]).read_bytes(), "label": label, "group": group, "src": "Field"})
    return out


def deepfakeface(n: int = 400, seed: int = 0, shards=(0, 6, 12, 18, 23)) -> list[dict]:
    """DeepFakeFace: real celebrity faces vs face swaps (InsightFace) and SD inpainting/text-to-image faces."""
    rows = []
    for s in shards:
        t = pq.read_table(_dl("juhi-neeved/deepfakeface-labeled", f"data/test-{s:05d}-of-00024.parquet"))
        rows += [{"bytes": _img_bytes(i), "label": int(b), "group": c, "src": "DeepFakeFace"}
                 for i, b, c in zip(t["image"].to_pylist(), t["binary_label"].to_pylist(), t["class_name"].to_pylist())]
    return _balanced(rows, n, seed)


def tampered(n: int = 300, seed: int = 0, shards=(0, 20, 40, 62)) -> list[dict]:
    """Classic tampering benchmarks (CASIA, Columbia, Coverage, etc.) with ground-truth masks."""
    rows = []
    for s in shards:
        t = pq.read_table(_dl("KhangTruong/Tampered-Images-Combined-Dataset-2", f"data/cross_test-{s:05d}.parquet"),
                          columns=["image", "mask", "label", "dataset", "method"])
        rows += [{"bytes": _img_bytes(i), "mask": _img_bytes(m), "label": int(l), "group": f"{d}:{me}", "src": "Tampered"}
                 for i, m, l, d, me in zip(t["image"].to_pylist(), t["mask"].to_pylist(), t["label"].to_pylist(),
                                           t["dataset"].to_pylist(), t["method"].to_pylist())]
    return _balanced(rows, n, seed)


def in_the_wild(n: int = 300, seed: int = 0, shard: int = 3) -> list[dict]:
    """In-the-Wild: real celebrity/politician speech vs deepfakes collected online."""
    t = pq.read_table(_dl("SpeechAntiSpoofingBenchmarks/InTheWild", f"data/test-{shard:05d}-of-00008.parquet"))
    cols = t.column_names
    aud = t["audio"].to_pylist()
    lab = t["label"].to_pylist()
    rows = [{"bytes": _img_bytes(a), "label": int(l), "group": "spoof" if int(l) else "bonafide", "src": "InTheWild"}
            for a, l in zip(aud, lab)]
    return _balanced(rows, n, seed)


def elevenlabs(n: int = 300, seed: int = 0) -> list[dict]:
    rows = []
    for f in ("data/train-00000-of-00002.parquet", "data/train-00001-of-00002.parquet"):
        t = pq.read_table(_dl("garystafford/deepfake-audio-detection", f))
        rows += [{"bytes": _img_bytes(a), "label": int(l), "group": "fake" if int(l) else "real", "src": "ElevenLabsSet"}
                 for a, l in zip(t["audio"].to_pylist(), t["label"].to_pylist())]
    return _balanced(rows, n, seed)


IMAGE_AI_SETS = {"GenImage": tinygen, "CommunityForensics": cfeval, "WebArt": webart, "Field": field}
