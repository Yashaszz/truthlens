"""Lazy loaders for pretrained models. Every call degrades gracefully: on failure it returns None
and the caller records a limitation instead of crashing the analysis."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from .config import ENABLE_MODELS, ENABLE_WHISPER, MODELS, WHISPER_MODEL

log = logging.getLogger("truthlens.models")
_lock = threading.Lock()
_pipes: dict = {}
_errors: dict[str, str] = {}
_whisper = None


def _device() -> int:
    try:
        import torch
        return 0 if torch.cuda.is_available() else -1
    except Exception:
        return -1


def device_name() -> str:
    try:
        import torch
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _pipe(key: str, task: str):
    if not ENABLE_MODELS:
        _errors[key] = "disabled by configuration"
        return None
    with _lock:
        if key in _pipes:
            return _pipes[key]
        if key in _errors:
            return None
        try:
            from transformers import pipeline
            _pipes[key] = pipeline(task, model=MODELS[key], device=_device(), top_k=None)
            log.info("loaded %s", MODELS[key])
        except Exception as e:  # pragma: no cover
            log.exception("model load failed: %s", key)
            _errors[key] = f"{type(e).__name__}: {e}"
            _pipes[key] = None
        return _pipes[key]


def _prob(result: list[dict], label: str) -> float:
    for r in result:
        if r["label"].lower() == label.lower():
            return float(r["score"])
    return float("nan")


def face_deepfake_probs(images) -> list[float] | None:
    """P(Deepfake) for each face crop (PIL images)."""
    p = _pipe("face_deepfake", "image-classification")
    if p is None or not images:
        return None if p is None else []
    out = p(images, batch_size=16)
    return [_prob(r, "Deepfake") for r in out]


def ai_image_prob(image) -> float | None:
    """P(artificial) for a whole image."""
    p = _pipe("ai_image", "image-classification")
    if p is None:
        return None
    return _prob(p(image), "artificial")


def audio_spoof_probs(chunks, sr: int = 16000) -> list[float] | None:
    """P(fake) for each mono float32 waveform chunk sampled at 16 kHz."""
    p = _pipe("audio_spoof", "audio-classification")
    if p is None or not chunks:
        return None if p is None else []
    out = p([{"raw": c, "sampling_rate": sr} for c in chunks], batch_size=8)
    return [_prob(r, "fake") for r in out]


def _add_cuda_dlls():
    """Let ctranslate2 (faster-whisper) find the cuDNN/cuBLAS DLLs bundled with torch on Windows."""
    try:
        import torch
        lib = Path(torch.__file__).parent / "lib"
        if lib.exists() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _load_whisper(force_cpu: bool = False):
    global _whisper
    from faster_whisper import WhisperModel
    if not force_cpu and _device() == 0:
        _add_cuda_dlls()
        _whisper = (WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16"), "cuda")
    else:
        _whisper = (WhisperModel(WHISPER_MODEL if not force_cpu else "base", device="cpu",
                                 compute_type="int8"), "cpu")


def transcribe(wav_path: Path) -> dict | None:
    if not ENABLE_WHISPER:
        _errors["whisper"] = "disabled by configuration"
        return None
    with _lock:
        try:
            if _whisper is None:
                _load_whisper()
            return _run_whisper(wav_path)
        except Exception as e:
            log.warning("whisper on %s failed (%s); retrying on CPU", _whisper and _whisper[1], e)
            try:
                _load_whisper(force_cpu=True)
                return _run_whisper(wav_path)
            except Exception as e2:  # pragma: no cover
                _errors["whisper"] = f"{type(e2).__name__}: {e2}"
                return None


def _run_whisper(wav_path: Path) -> dict:
    model, dev = _whisper
    segments, info = model.transcribe(str(wav_path), word_timestamps=True, vad_filter=True, beam_size=3)
    segs = []
    for s in segments:
        segs.append({
            "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
            "avg_logprob": round(s.avg_logprob, 3), "no_speech_prob": round(s.no_speech_prob, 3),
            "words": [{"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2),
                       "p": round(w.probability, 3)} for w in (s.words or [])],
        })
    return {"language": info.language, "language_probability": round(info.language_probability, 3),
            "duration": round(info.duration, 2), "segments": segs,
            "text": " ".join(s["text"] for s in segs), "model": f"faster-whisper-{WHISPER_MODEL} ({dev})"}


def status() -> dict:
    return {"enabled": ENABLE_MODELS, "device": device_name(), "models": MODELS,
            "whisper": WHISPER_MODEL, "loaded": [k for k, v in _pipes.items() if v is not None],
            "errors": dict(_errors)}


def model_error(key: str) -> str | None:
    return _errors.get(key)
