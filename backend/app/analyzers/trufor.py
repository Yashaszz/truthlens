"""TruFor (Guillaro et al., CVPR 2023, GRIP-UNINA): learned image-forgery detection + localization.
Returns a global integrity score, a per-pixel manipulation heatmap and a reliability (confidence) map.
Licence: non-profit / informational use only (see third_party/trufor/LICENSE.txt)."""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
from pathlib import Path

import numpy as np
import torch
from PIL import Image

log = logging.getLogger("truthlens.trufor")
CODE = Path(__file__).resolve().parents[2] / "third_party" / "trufor"
WEIGHTS = Path(os.getenv("TRUFOR_WEIGHTS", Path(os.getenv("LOCALAPPDATA", Path.home() / ".cache")) / "truthlens" / "models" / "trufor" / "weights" / "trufor.pth.tar"))
MAX_SIDE = int(os.getenv("TRUFOR_MAX_SIDE", "1280"))
_lock = threading.Lock()
_model = None
_error = None


ENABLED = os.getenv("TRUTHLENS_TRUFOR", "0") == "1"  # opt-in: runs third-party research code (non-profit licence)


def available() -> bool:
    return ENABLED and CODE.exists() and WEIGHTS.exists()


def installed() -> bool:
    return CODE.exists() and WEIGHTS.exists()


def _load():
    global _model, _error
    if _model is not None or _error is not None:
        return _model
    try:
        if str(CODE) not in sys.path:
            sys.path.insert(0, str(CODE))  # its modules import each other as top-level "models.*"
        spec = importlib.util.spec_from_file_location("trufor_config", CODE / "config.py")
        cfgmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfgmod)
        cfg = cfgmod._C.clone()
        cfg.defrost()
        cfg.merge_from_file(str(CODE / "trufor.yaml"))
        cfg.MODEL.PRETRAINED = ""
        cfg.freeze()
        from models.cmx.builder_np_conf import myEncoderDecoder
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        # weights_only=True: tensors only, never unpickle arbitrary objects from a downloaded file
        ckpt = torch.load(str(WEIGHTS), map_location=dev, weights_only=True)
        m = myEncoderDecoder(cfg=cfg)
        m.load_state_dict(ckpt["state_dict"])
        _model = (m.to(dev).eval(), dev)
        log.info("TruFor loaded on %s", dev)
    except Exception as e:  # pragma: no cover
        _error = f"{type(e).__name__}: {e}"
        log.exception("TruFor failed to load")
    return _model


def error() -> str | None:
    return _error if _error else (None if available() else "TruFor weights not installed")


@torch.no_grad()
def analyze(pil: Image.Image) -> dict | None:
    """{'score': P(manipulated), 'map': HxW float32 in [0,1], 'conf': HxW, 'scale': resize factor} or None."""
    if not available():
        return None
    with _lock:
        loaded = _load()
        if loaded is None:
            return None
        model, dev = loaded
        rgb = pil.convert("RGB")
        scale = 1.0
        if max(rgb.size) > MAX_SIDE:
            scale = MAX_SIDE / max(rgb.size)
            rgb = rgb.resize((max(64, int(rgb.width * scale)), max(64, int(rgb.height * scale))), Image.BICUBIC)
        x = torch.tensor(np.asarray(rgb).transpose(2, 0, 1), dtype=torch.float32).unsqueeze(0).to(dev) / 256.0
        try:
            pred, conf, det, _ = model(x)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            rgb = rgb.resize((rgb.width // 2, rgb.height // 2), Image.BICUBIC)
            scale /= 2
            x = torch.tensor(np.asarray(rgb).transpose(2, 0, 1), dtype=torch.float32).unsqueeze(0).to(dev) / 256.0
            pred, conf, det, _ = model(x)
        hm = torch.softmax(pred.squeeze(0), dim=0)[1].float().cpu().numpy()
        cf = torch.sigmoid(conf.squeeze(0))[0].float().cpu().numpy() if conf is not None else None
        score = float(torch.sigmoid(det).item()) if det is not None else float(np.percentile(hm, 99))
        if dev == "cuda":
            torch.cuda.empty_cache()
        return {"score": score, "map": hm.astype(np.float32), "conf": None if cf is None else cf.astype(np.float32), "scale": scale}
