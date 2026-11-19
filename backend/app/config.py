"""Central configuration for TruthLens."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TRUTHLENS_DATA", BASE_DIR / "data" / "cases"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_VERSION = "0.1.0"

# Pretrained checkpoints (verified on HuggingFace). No training is done in this prototype.
MODELS = {
    "face_deepfake": "prithivMLmods/Deep-Fake-Detector-v2-Model",   # ViT, labels: Realism / Deepfake
    "ai_image": "umm-maybe/AI-image-detector",                     # Swin, labels: artificial / human
    "audio_spoof": "MelodyMachine/Deepfake-audio-detection-V2",    # wav2vec2, labels: fake / real
}
WHISPER_MODEL = os.getenv("TRUTHLENS_WHISPER", "small")

# Set TRUTHLENS_MODELS=0 to run only the classical (signal-processing) detectors.
ENABLE_MODELS = os.getenv("TRUTHLENS_MODELS", "1") == "1"
ENABLE_WHISPER = os.getenv("TRUTHLENS_WHISPER_ON", "1") == "1"

# Analysis limits (keep the demo responsive on a laptop GPU)
VIDEO_SAMPLE_FPS = 2.0
VIDEO_MAX_SAMPLES = 60
VIDEO_MAX_SECONDS = 120
AUDIO_MAX_SECONDS = 180
AUDIO_WINDOW_S = 4.0
AUDIO_HOP_S = 2.0

# Per-check modes chosen in the UI. "standard" equals the module defaults above.
MODES = {
    "quick": {"video_sample_fps": 1.0, "video_max_samples": 24, "video_max_seconds": 60,
              "audio_max_seconds": 90, "audio_hop_s": 4.0},
    "standard": {"video_sample_fps": VIDEO_SAMPLE_FPS, "video_max_samples": VIDEO_MAX_SAMPLES,
                 "video_max_seconds": VIDEO_MAX_SECONDS, "audio_max_seconds": AUDIO_MAX_SECONDS, "audio_hop_s": AUDIO_HOP_S},
    "thorough": {"video_sample_fps": 4.0, "video_max_samples": 160, "video_max_seconds": 300,
                 "audio_max_seconds": 300, "audio_hop_s": 1.0},
}


def resolve_options(raw: dict | None) -> dict:
    raw = raw or {}
    mode = raw.get("mode") if raw.get("mode") in MODES else "standard"
    return {"mode": mode, "models": bool(raw.get("models", True)) and ENABLE_MODELS,
            "transcribe": bool(raw.get("transcribe", True)) and ENABLE_WHISPER,
            "lipsync": bool(raw.get("lipsync", True)), **MODES[mode]}


# Fusion: importance of each detector (multiplied by its per-run reliability).
DETECTOR_IMPORTANCE = {
    "generator_metadata": 4.0,
    "ai_image_model": 1.2,
    "face_deepfake_model": 1.3,
    "audio_spoof_model": 1.3,
    "ela": 0.8,
    "noise_residual": 0.6,
    "jpeg_grid": 0.5,
    "copy_move": 0.9,
    "exif_software": 0.6,
    "exif_missing": 0.3,
    "exif_dates": 0.5,
    "face_sharpness": 0.5,
    "temporal_cuts": 0.5,
    "frozen_frames": 0.4,
    "video_container": 0.3,
    "audio_bandwidth": 0.4,
    "digital_silence": 0.6,
    "noise_floor_jumps": 0.6,
    "pitch_smoothness": 0.3,
    "av_sync": 1.0,
    "quote_check": 1.0,
    "topic_overlap": 0.5,
    "date_consistency": 0.7,
    "transcript_match": 0.9,
    "sensational_language": 0.25,
    "cross_modal": 1.2,
}
