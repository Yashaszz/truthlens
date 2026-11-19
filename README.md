# TruthLens: Multimodal Digital Forensics & Deepfake Detection

InnovEdge Hackathon 2026, Problem Statement 04.

TruthLens ingests **image, video, audio and text** evidence, runs per-modality forensic detectors,
**correlates signals across modalities**, fuses them into a **calibrated, explainable assessment with an
uncertainty band**, and exports a **traceable forensic report** with chain of custody. Scores are presented
as indicators for a human examiner, never as verdicts.

## Architecture

```
            ┌─────────── INGEST: SHA-256, read-only originals, custody log ───────────┐
Image ──► EXIF/generator metadata · texture-normalised ELA · noise residual · JPEG/DCT grid
          · ORB copy-move · Swin AI-image classifier · ViT face-deepfake classifier ─────────┐
Video ──► FFmpeg/OpenCV single pass ─► face tracking ─► ViT face deepfake (sampled frames)   │
          · face-blend sharpness · scene cuts · frozen frames · container tags · keyframe ELA│
          └► audio track ─► (Audio pipeline) ─► Whisper word timestamps                      ├─► CORRELATE ─► FUSION ─► REPORT
Audio ──► wav2vec2 anti-spoof (4 s windows) · MFCC/ZCR/flatness · digital-silence splices    │   temporal convergence   reliability-   HTML / JSON
          · noise-floor jumps · bandwidth · prosody · Whisper transcript                     │   face/voice/sync        weighted       findings, locations,
Sync  ──► mouth-region motion × speech-energy cross-correlation (±0.6 s lag)                 │   pattern, provenance,   log-odds +     confidence, caveats,
Text  ──► quotes vs transcript · caption topic vs speech · dates vs metadata · supplied      │   claim-vs-media         uncertainty    human checks, custody
          transcripts · framing language ───────────────────────────────────────────────────┘                          band
```

**Pretrained models (no training required):**
| Purpose | Model |
|---|---|
| Face deepfake (ViT) | `prithivMLmods/Deep-Fake-Detector-v2-Model` |
| AI-generated image (Swin) | `umm-maybe/AI-image-detector` |
| Synthetic voice (wav2vec2) | `MelodyMachine/Deepfake-audio-detection-V2` |
| Speech-to-text + word timing | `faster-whisper` (`small`) |

Every model failure degrades gracefully: the classical detectors still run and the report lists the limitation.

## Run

```powershell
# backend (first time)
cd backend
python -m venv .venv
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu124
.venv\Scripts\pip install -r requirements.txt
# start API on :8000
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

```powershell
# frontend (dev, proxies /api to :8000)
cd frontend
npm install
npm run dev        # http://localhost:5173
```

For the demo you can instead run `npm run build` once; the API then serves the UI itself at http://localhost:8000.

Environment switches: `TRUTHLENS_MODELS=0` (classical detectors only), `TRUTHLENS_WHISPER=base` (faster ASR),
`TRUTHLENS_WHISPER_ON=0` (skip ASR).

Test media: `backend\.venv\Scripts\python backend\scripts\make_samples.py` builds a tampered photo, spliced TTS
audio, a "dubbed" still-image video and a misleading caption in `samples/`.

## Forensic-trust principles implemented
- Originals hashed on ingest, stored read-only, re-verified at report time; every action is logged to `custody.jsonl`.
- Each finding records **what** (indicator), **where** (region / frame / timestamp / segment / metadata field),
  **how sure** (score + detector reliability), **limitations** and **alternative explanations**.
- Fusion is transparent: drivers that raise or lower suspicion are listed; disagreement widens the uncertainty band;
  a neutral prior prevents confident output from thin evidence.
- Examiners confirm / dismiss / follow up each finding; reviews are written into the chain of custody and report.
- Honest caveat: detector reliability weights are expert priors and have not been calibrated on a labelled benchmark.
