"""Production detector wrappers + calibrated ensembles. The benchmark harness (backend/eval) measures exactly
these classes; calibration files in app/calib/ are produced by eval scripts from labelled public datasets."""
from __future__ import annotations

import io
import json
import logging
import threading
from pathlib import Path

import numpy as np
import torch
from PIL import Image

log = logging.getLogger("truthlens.detectors")
DEV = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEV == "cuda" else torch.float32
CALIB = Path(__file__).resolve().parent / "calib"
FAKE_WORDS = {"artificial", "ai", "fake", "deepfake", "dalle", "sd", "generated", "synthetic", "spoof", "aivoice"}


def to_pil(x) -> Image.Image:
    return (Image.open(io.BytesIO(x)) if isinstance(x, (bytes, bytearray)) else x).convert("RGB")


def logit(p):
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


class HFClassifier:
    """transformers image classifier → P(fake) (softmax mass on labels meaning 'fake')."""

    def __init__(self, repo: str, fake_labels: set[str] | None = None):
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        self.name = repo
        self.proc = AutoImageProcessor.from_pretrained(repo)
        self.model = AutoModelForImageClassification.from_pretrained(repo, torch_dtype=DTYPE).to(DEV).eval()
        labels = {int(k): v for k, v in self.model.config.id2label.items()}
        fl = fake_labels or FAKE_WORDS
        self.fake_idx = [i for i, n in labels.items() if n.lower() in fl]
        if not self.fake_idx:
            raise ValueError(f"no fake label in {labels}")

    @torch.no_grad()
    def predict(self, images: list, bs: int = 16) -> np.ndarray:
        out = []
        for i in range(0, len(images), bs):
            batch = [to_pil(x) for x in images[i:i + bs]]
            inp = self.proc(images=batch, return_tensors="pt").to(DEV)
            inp = {k: (v.to(self.model.dtype) if v.is_floating_point() else v) for k, v in inp.items()}
            out.append(self.model(**inp).logits.float().softmax(-1)[:, self.fake_idx].sum(-1).cpu().numpy())
        return np.concatenate(out) if out else np.array([])


class CommunityForensicsViT:
    """Community Forensics ViT-S (CVPR 2025; 4,803 generators). Sigmoid output; CLIP preprocessing done by hand
    (resize short side 440, centre-crop 384) so behaviour doesn't depend on the transformers version."""

    def __init__(self, repo: str = "buildborderless/CommunityForensics-DeepfakeDet-ViT"):
        from transformers import ViTForImageClassification
        self.name = repo
        self.model = ViTForImageClassification.from_pretrained(repo, torch_dtype=DTYPE).to(DEV).eval()
        if self.model.config.num_labels != 1:
            raise ValueError("unexpected CommunityForensics config (re-download the model)")
        self.mean = torch.tensor([0.48145466, 0.4578275, 0.40821073]).view(3, 1, 1)
        self.std = torch.tensor([0.26862954, 0.26130258, 0.27577711]).view(3, 1, 1)

    def _prep(self, im: Image.Image, crop: bool = True) -> torch.Tensor:
        w, h = im.size
        if crop:
            s = 440 / min(w, h)
            im = im.resize((max(384, round(w * s)), max(384, round(h * s))), Image.BICUBIC)
            w, h = im.size
            l, t = (w - 384) // 2, (h - 384) // 2
            im = im.crop((l, t, l + 384, t + 384))
        else:
            im = im.resize((384, 384), Image.BICUBIC)
        x = torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0).permute(2, 0, 1)
        return (x - self.mean) / self.std

    @torch.no_grad()
    def predict(self, images: list, bs: int = 16, crop: bool = True) -> np.ndarray:
        out = []
        for i in range(0, len(images), bs):
            x = torch.stack([self._prep(to_pil(b), crop) for b in images[i:i + bs]]).to(DEV, self.model.dtype)
            out.append(torch.sigmoid(self.model(pixel_values=x).logits.float()).squeeze(-1).cpu().numpy())
        return np.concatenate(out) if out else np.array([])


MODEL_FACTORY = {
    "CommunityForensics ViT": lambda: CommunityForensicsViT(),
    "haywoodsloan SwinV2": lambda: HFClassifier("haywoodsloan/ai-image-detector-deploy"),
    "umm-maybe (current)": lambda: HFClassifier("umm-maybe/AI-image-detector"),
    "Smogy Swin": lambda: HFClassifier("Smogy/SMOGY-Ai-images-detector"),
    "Organika SDXL": lambda: HFClassifier("Organika/sdxl-detector"),
    "prithiv DeepFake v2 (current)": lambda: HFClassifier("prithivMLmods/Deep-Fake-Detector-v2-Model"),
    "dima806 deepfake ViT": lambda: HFClassifier("dima806/deepfake_vs_real_image_detection"),
}

_lock = threading.Lock()
_cache: dict = {}
_errors: dict = {}


def get(name: str):
    with _lock:
        if name in _cache:
            return _cache[name]
        if name in _errors:
            return None
        try:
            _cache[name] = MODEL_FACTORY[name]()
            log.info("loaded %s", name)
        except Exception as e:  # pragma: no cover
            log.exception("failed to load %s", name)
            _errors[name] = f"{type(e).__name__}: {e}"
            _cache[name] = None
        return _cache[name]


def load_calib(name: str) -> dict | None:
    p = CALIB / f"{name}.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def quality_features(images: list) -> np.ndarray:
    """How degraded each image is (sharpness, noise, JPEG blockiness). Lets the calibrated stack adapt to
    laundered media: compression/noise weaken generator fingerprints, blur makes real photos look synthetic."""
    import cv2
    out = []
    for im in images:
        g = np.asarray(to_pil(im).convert("L"), dtype=np.float32)
        s = 512 / max(g.shape)
        if s < 1:
            g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        sharp = np.log1p(cv2.Laplacian(g, cv2.CV_32F).var())
        noise = np.log1p((g - cv2.medianBlur(g.astype(np.uint8), 3).astype(np.float32)).std())
        dx = np.abs(np.diff(g, axis=1)).mean(axis=0)
        ph = np.array([dx[i::8].mean() for i in range(8)])
        blk = float(ph.max() / (np.median(ph) + 1e-6))
        out.append([sharp, noise, blk])
    return np.array(out, dtype=np.float64)


def stack_features(parts: dict, models: list, images: list | None, use_quality: bool) -> np.ndarray:
    # a member can return NaN on extreme inputs (fp16 overflow): treat as no opinion (0.5)
    L = np.stack([logit(np.nan_to_num(np.asarray(parts[m], dtype=np.float64), nan=0.5)) for m in models], axis=1)
    if not use_quality:
        return L
    Q = np.nan_to_num(quality_features(images), nan=0.0, posinf=10.0, neginf=0.0)
    return np.concatenate([L, Q, L[:, :1] * Q[:, :1], L[:, :1] * Q[:, 1:2]], axis=1)  # strongest member × quality


class CalibratedEnsemble:
    """Logistic-regression stack over member logits (+ optional image-quality features), fitted by eval scripts."""

    def __init__(self, calib_name: str, fallback_models: list[str]):
        self.calib = load_calib(calib_name)
        self.models = self.calib["models"] if self.calib else fallback_models
        self.name = calib_name

    def members(self):
        return [(m, get(m)) for m in self.models]

    def predict(self, images: list) -> dict:
        parts = {}
        for m, det in self.members():
            if det is not None:
                parts[m] = det.predict(images)
        if not parts:
            return {"p": None, "parts": {}, "calibrated": False}
        if self.calib and all(m in parts for m in self.models):
            X = stack_features(parts, self.models, images, bool(self.calib.get("quality")))
            if "mean" in self.calib:
                X = (X - np.array(self.calib["mean"])) / np.array(self.calib["scale"])
            z = X @ np.array(self.calib["coef"]) + self.calib["intercept"]
            p = 1 / (1 + np.exp(-z))
            calibrated = True
        else:  # degrade gracefully: mean of available members
            p = np.mean([parts[m] for m in parts], axis=0)
            calibrated = False
        return {"p": p, "parts": {k: v for k, v in parts.items()}, "calibrated": calibrated}


AI_IMAGE = CalibratedEnsemble("ai_image", ["CommunityForensics ViT", "haywoodsloan SwinV2", "umm-maybe (current)"])


class AudioClassifier:
    def __init__(self, repo: str, fake: set[str]):
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        self.name = repo
        self.fe = AutoFeatureExtractor.from_pretrained(repo)
        self.model = AutoModelForAudioClassification.from_pretrained(repo).to(DEV).eval()
        self.idx = [int(k) for k, v in self.model.config.id2label.items() if v.lower() in fake]
        if not self.idx:
            raise ValueError(f"no fake label in {self.model.config.id2label}")

    @torch.no_grad()
    def predict(self, waves: list, bs: int = 8) -> np.ndarray:
        out = []
        for i in range(0, len(waves), bs):
            inp = self.fe(waves[i:i + bs], sampling_rate=16000, return_tensors="pt", padding=True)
            inp = {k: v.to(DEV) for k, v in inp.items()}
            out.append(self.model(**inp).logits.float().softmax(-1)[:, self.idx].sum(-1).cpu().numpy())
        return np.concatenate(out) if out else np.array([])


MODEL_FACTORY.update({
    "mo-thecreator": lambda: AudioClassifier("mo-thecreator/Deepfake-audio-detection", {"fake"}),
    "Gustking XLSR-large": lambda: AudioClassifier("Gustking/wav2vec2-large-xlsr-deepfake-audio-classification", {"fake"}),
})
VOICE = CalibratedEnsemble("voice", ["mo-thecreator", "Gustking XLSR-large"])


class FaceSwapHead:
    """Logistic head on Community Forensics ViT CLS features, trained on DeepFakeFace (eval/train_face_head.py)."""

    def __init__(self):
        self.ok = (CALIB / "face_head.npz").exists()
        self.meta = load_calib("face_head") or {}
        if self.ok:
            z = np.load(CALIB / "face_head.npz")
            self.mean, self.scale, self.coef, self.b = z["mean"], z["scale"], z["coef"], float(z["intercept"][0])

    @torch.no_grad()
    def predict(self, crops: list) -> np.ndarray | None:
        cf = get("CommunityForensics ViT")
        if cf is None or not crops:
            return None
        x = torch.stack([cf._prep(to_pil(c)) for c in crops]).to(DEV, cf.model.dtype)
        h = cf.model.vit(pixel_values=x).last_hidden_state[:, 0, :].float().cpu().numpy()
        if not self.ok:  # fall back to the backbone's own AI-generated logit
            return torch.sigmoid(cf.model.classifier(torch.from_numpy(h).to(DEV, cf.model.dtype)).float()).squeeze(-1).cpu().numpy()
        z = ((h - self.mean) / self.scale) @ self.coef + self.b
        return 1 / (1 + np.exp(-z))


FACE = FaceSwapHead()


def errors() -> dict:
    return dict(_errors)
