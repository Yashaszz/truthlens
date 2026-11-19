"""Benchmark face-swap detectors (DeepFakeFace) and voice-deepfake detectors (In-the-Wild, ElevenLabs set).
Usage: python -m eval.bench_faces_audio [faces|audio|all] [N]"""
from __future__ import annotations

import gc
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
import torch

from .image_models import HFClassifier, CommunityForensicsViT, timed_predict, DEV
from .metrics import summarize
from .sources import deepfakeface, elevenlabs, in_the_wild

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

FACE_CANDIDATES = {
    "prithiv DeepFake v2 (current)": lambda: HFClassifier("prithivMLmods/Deep-Fake-Detector-v2-Model"),
    "dima806 deepfake ViT": lambda: HFClassifier("dima806/deepfake_vs_real_image_detection"),
    "prithiv SigLIP2 3-way": lambda: HFClassifier("prithivMLmods/AI-vs-Deepfake-vs-Real-Siglip2"),
    "CommunityForensics ViT": lambda: CommunityForensicsViT(),
    "haywoodsloan SwinV2": lambda: HFClassifier("haywoodsloan/ai-image-detector-deploy"),
    "Ateeqq SigLIP": lambda: HFClassifier("Ateeqq/ai-vs-human-image-detector"),
}

AUDIO_CANDIDATES = {
    "MelodyMachine V2 (current)": ("MelodyMachine/Deepfake-audio-detection-V2", {"fake"}),
    "mo-thecreator": ("mo-thecreator/Deepfake-audio-detection", {"fake"}),
    "garystafford wav2vec2*": ("garystafford/wav2vec2-deepfake-voice-detector", {"fake"}),
    "Gustking XLSR-large": ("Gustking/wav2vec2-large-xlsr-deepfake-audio-classification", {"fake"}),
    "Om-Parab distilhubert*": ("Om-Parab/distilhubert-finetuned-audio-deepfake-in-the-wild", {"spoof"}),
    "Vansh180 wav2vec2": ("Vansh180/deepfake-audio-wav2vec2", {"fake"}),
    "Hemgg wav2vec2": ("Hemgg/Deepfake-audio-detection", {"aivoice"}),
}


def decode_audio(b: bytes, sr: int = 16000, max_s: float = 8.0) -> np.ndarray:
    y, s = sf.read(io.BytesIO(b), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if s != sr:
        import librosa
        y = librosa.resample(y, orig_sr=s, target_sr=sr)
    return y[: int(sr * max_s)]


class AudioClassifier:
    def __init__(self, repo: str, fake: set[str]):
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        self.fe = AutoFeatureExtractor.from_pretrained(repo)
        self.model = AutoModelForAudioClassification.from_pretrained(repo).to(DEV).eval()
        self.idx = [int(k) for k, v in self.model.config.id2label.items() if v.lower() in fake]
        assert self.idx

    @torch.no_grad()
    def predict(self, waves: list[np.ndarray], bs: int = 8) -> np.ndarray:
        out = []
        for i in range(0, len(waves), bs):
            b = waves[i:i + bs]
            inp = self.fe(b, sampling_rate=16000, return_tensors="pt", padding=True)
            inp = {k: v.to(DEV) for k, v in inp.items()}
            out.append(self.model(**inp).logits.float().softmax(-1)[:, self.idx].sum(-1).cpu().numpy())
        return np.concatenate(out)


def run(kind: str, n: int):
    rows = []
    if kind in ("faces", "all"):
        data = {"DeepFakeFace": deepfakeface(n)}
        for name, d in data.items():
            print(f"[data] {name}: {len(d)} ({sum(r['label'] for r in d)} fake) groups={sorted({r['group'] for r in d})}", flush=True)
        for mname, make in FACE_CANDIDATES.items():
            det = make()
            for sname, d in data.items():
                p, per = timed_predict(det, [r["bytes"] for r in d])
                rows += [{"task": "face", "model": mname, "set": sname, "group": r["group"], "label": r["label"], "p": float(x), "sec": per} for r, x in zip(d, p)]
                s = summarize([r["label"] for r in d], p)
                print(f"[{mname:28s}] {sname:14s} AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f} TPR={s['tpr@0.5']:.2f} TNR={s['tnr@0.5']:.2f} {per * 1000:.0f} ms", flush=True)
            del det; gc.collect(); torch.cuda.empty_cache()
    if kind in ("audio", "all"):
        data = {"InTheWild": in_the_wild(n), "ElevenLabsSet": elevenlabs(n)}
        waves = {}
        for name, d in data.items():
            waves[name] = [decode_audio(r["bytes"]) for r in d]
            print(f"[data] {name}: {len(d)} ({sum(r['label'] for r in d)} fake)", flush=True)
        for mname, (repo, fake) in AUDIO_CANDIDATES.items():
            try:
                det = AudioClassifier(repo, fake)
            except Exception as e:
                print(f"[skip] {mname}: {e}", flush=True); continue
            for sname, d in data.items():
                t = time.time(); p = det.predict(waves[sname]); per = (time.time() - t) / len(d)
                rows += [{"task": "audio", "model": mname, "set": sname, "group": r["group"], "label": r["label"], "p": float(x), "sec": per} for r, x in zip(d, p)]
                s = summarize([r["label"] for r in d], p)
                print(f"[{mname:28s}] {sname:14s} AUC={s['auc']:.3f} acc={s['acc@0.5']:.3f} TPR={s['tpr@0.5']:.2f} TNR={s['tnr@0.5']:.2f} {per * 1000:.0f} ms", flush=True)
            del det; gc.collect(); torch.cuda.empty_cache()
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"{kind}_scores.csv", index=False)
    summ = {}
    for (task, m, s), g in df.groupby(["task", "model", "set"]):
        summ.setdefault(task, {}).setdefault(m, {})[s] = summarize(g["label"].values, g["p"].values)
    (OUT / f"{kind}_summary.json").write_text(json.dumps(summ, indent=2))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "all", int(sys.argv[2]) if len(sys.argv) > 2 else 300)
