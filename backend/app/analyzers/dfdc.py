"""Video face-swap detector: the Kaggle DeepFake Detection Challenge winning model (selimsef, MIT licence).
EfficientNet-B7 (Noisy Student) + linear head, trained on DFDC's 100k+ real/face-swapped videos.
The architecture is re-declared here (no third-party code is executed); only the released weights are loaded,
in torch's safe weights-only mode. Preprocessing and the per-video 'confident strategy' follow the original repo."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

log = logging.getLogger("truthlens.dfdc")
WDIR = Path(os.getenv("DFDC_WEIGHTS", Path(os.getenv("LOCALAPPDATA", Path.home() / ".cache")) / "truthlens" / "models" / "dfdc"))
CKPTS = ["final_999_DeepFakeClassifier_tf_efficientnet_b7_ns_0_23", "final_777_DeepFakeClassifier_tf_efficientnet_b7_ns_0_31"]
SIZE = 380
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
_lock = threading.Lock()
_models = None
_error = None


class DeepFakeClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        import timm
        self.encoder = timm.create_model("tf_efficientnet_b7.ns_jft_in1k", pretrained=False, drop_path_rate=0.2)
        self.avg_pool = nn.AdaptiveAvgPool2d((1, 1))
        self.dropout = nn.Dropout(0.0)
        self.fc = nn.Linear(2560, 1)

    def forward(self, x):
        x = self.encoder.forward_features(x)
        return self.fc(self.dropout(self.avg_pool(x).flatten(1)))


def available() -> bool:
    return any((WDIR / c).exists() for c in CKPTS)


def error():
    return _error


def _load():
    global _models, _error
    if _models is not None or _error is not None:
        return _models
    try:
        import re
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        ms = []
        for c in CKPTS:
            p = WDIR / c
            if not p.exists():
                continue
            # checkpoints were pickled with numpy 1.x paths; allow-list those plain numpy types by their old names
            from numpy._core.multiarray import scalar as _np_scalar
            safe = [(_np_scalar, "numpy.core.multiarray.scalar"), _np_scalar, np.dtype, np.dtypes.Float64DType]
            with torch.serialization.safe_globals(safe):
                ck = torch.load(str(p), map_location="cpu", weights_only=True)
            sd = ck.get("state_dict", ck)
            m = DeepFakeClassifier()
            m.load_state_dict({re.sub("^module.", "", k): v for k, v in sd.items()}, strict=True)
            ms.append(m.to(dev).eval().half() if dev == "cuda" else m.eval())
        _models = (ms, dev) if ms else None
        if not ms:
            _error = "no DFDC weights found"
        log.info("DFDC models loaded: %d", len(ms))
    except Exception as e:  # pragma: no cover
        _error = f"{type(e).__name__}: {e}"
        log.exception("DFDC load failed")
    return _models


def crop_face(frame_bgr: np.ndarray, box) -> np.ndarray:
    """Original recipe: pad the face box by a third of its size on every side."""
    x, y, w, h = box
    pw, ph = w // 3, h // 3
    H, W = frame_bgr.shape[:2]
    return frame_bgr[max(0, y - ph):min(H, y + h + ph), max(0, x - pw):min(W, x + w + pw)]


def _prep(face_bgr: np.ndarray) -> np.ndarray:
    h, w = face_bgr.shape[:2]
    s = SIZE / max(h, w)
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    face = cv2.resize(face_bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=interp)
    out = np.zeros((SIZE, SIZE, 3), np.uint8)
    fh, fw = face.shape[:2]
    out[(SIZE - fh) // 2:(SIZE - fh) // 2 + fh, (SIZE - fw) // 2:(SIZE - fw) // 2 + fw] = face
    rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return ((rgb - MEAN) / STD).transpose(2, 0, 1)


@torch.no_grad()
def predict_faces(faces_bgr: list, bs: int = 8) -> np.ndarray | None:
    """P(fake) per face crop, averaged over the loaded checkpoints."""
    with _lock:
        loaded = _load()
        if loaded is None or not faces_bgr:
            return None
        ms, dev = loaded
        x_all = np.stack([_prep(f) for f in faces_bgr])
        preds = []
        for i in range(0, len(x_all), bs):
            x = torch.from_numpy(x_all[i:i + bs]).to(dev)
            x = x.half() if dev == "cuda" else x
            preds.append(np.mean([torch.sigmoid(m(x).float()).squeeze(-1).cpu().numpy() for m in ms], axis=0))
        if dev == "cuda":
            torch.cuda.empty_cache()
        return np.concatenate(preds)


def confident_strategy(pred, t: float = 0.8) -> float:
    pred = np.asarray(pred, dtype=float)
    sz = len(pred)
    fakes = np.count_nonzero(pred > t)
    if fakes > sz // 2.5 and fakes > 11:
        return float(np.mean(pred[pred > t]))
    if np.count_nonzero(pred < 0.2) > 0.9 * sz:
        return float(np.mean(pred[pred < 0.2]))
    return float(np.mean(pred))
