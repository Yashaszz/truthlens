"""Uniform wrappers around candidate image detectors: each returns P(fake) per image."""
from __future__ import annotations

import io
import time

import numpy as np
import torch
from PIL import Image

DEV = "cuda" if torch.cuda.is_available() else "cpu"
FAKE_WORDS = {"artificial", "ai", "fake", "deepfake", "dalle", "sd", "generated", "synthetic"}


def to_pil(b) -> Image.Image:
    im = Image.open(io.BytesIO(b)) if isinstance(b, (bytes, bytearray)) else b
    return im.convert("RGB")


from app.detectors import HFClassifier, CommunityForensicsViT  # noqa: E402  (single source of truth)


AI_IMAGE_CANDIDATES = {
    "umm-maybe (current)": lambda: HFClassifier("umm-maybe/AI-image-detector"),
    "CommunityForensics ViT": lambda: CommunityForensicsViT(),
    "Organika SDXL": lambda: HFClassifier("Organika/sdxl-detector"),
    "haywoodsloan SwinV2": lambda: HFClassifier("haywoodsloan/ai-image-detector-deploy"),
    "Ateeqq SigLIP": lambda: HFClassifier("Ateeqq/ai-vs-human-image-detector"),
    "dima806 ViT": lambda: HFClassifier("dima806/ai_vs_real_image_detection"),
    "Smogy Swin": lambda: HFClassifier("Smogy/SMOGY-Ai-images-detector"),
    "prithiv SigLIP2 3-way": lambda: HFClassifier("prithivMLmods/AI-vs-Deepfake-vs-Real-Siglip2"),
    "NYUAD ViT": lambda: HFClassifier("NYUAD-ComNets/NYUAD_AI-generated_images_detector"),
}


def timed_predict(det, images) -> tuple[np.ndarray, float]:
    if DEV == "cuda":
        torch.cuda.synchronize()
    t = time.time()
    p = det.predict(images)
    if DEV == "cuda":
        torch.cuda.synchronize()
    return p, (time.time() - t) / max(1, len(images))
