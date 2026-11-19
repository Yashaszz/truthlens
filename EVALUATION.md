# TruthLens: Detector Evaluation

Every detector TruthLens ships was **chosen by benchmark** and **calibrated on labelled public data**. This page
lists what was tested, how, and the honest results, including the weak spots. All numbers can be reproduced
with the scripts in `backend/eval/`, which use the production detector classes in `backend/app/detectors.py`.

* **AUC**: 0.5 = guessing, 1.0 = perfect ranking. **Accuracy** at a 50 % threshold. **TPR** = share of fakes caught,
  **TNR** = share of genuine media correctly cleared. **ECE** = calibration error (how far "80 %" is from 80 % in reality).
* "Held-out" means the data was **not** used to choose or fit the model being scored.
* Dataset/model pairs marked \* were excluded from conclusions because the model was trained on that dataset (leakage).

---

## 1. AI-generated images

**Data** (400 balanced samples each): GenImage-tiny (ImageNet vs ADM, BigGAN, GLIDE, Midjourney, SD 1.4/1.5, VQDM,
Wukong) · Community Forensics Eval (CVPR 2025, COCO/FFHQ vs many recent generators) · WebArt (AI art vs real
photos/art scraped from the web) · Field (4 images uploaded during development, labelled by a human).

| Detector | GenImage | CommunityForensics | WebArt | Field |
|---|---|---|---|---|
| umm-maybe/AI-image-detector (**previous**) | 0.738 | 0.562 | 0.634 | 0.333 |
| **buildborderless/CommunityForensics-DeepfakeDet-ViT** | **0.995** | **0.988** | 0.666 | **1.000** |
| Smogy/SMOGY-Ai-images-detector | 0.832 | 0.766 | 0.776 | 0.333 |
| haywoodsloan/ai-image-detector-deploy | 0.778 | 0.778 | 0.665 | 1.000 |
| Organika/sdxl-detector | 0.724 | 0.720 | 0.712 | 0.333 |
| dima806/ai_vs_real_image_detection | 0.669 | 0.717 | 0.998\* | 0.667 |
| Ateeqq/ai-vs-human-image-detector | 0.549 | 0.578 | 0.409 | 0.333 |
| prithivMLmods/AI-vs-Deepfake-vs-Real-Siglip2 | 0.358 | 0.682 | 0.376 | 0.333 |

**Shipped:** logistic-regression ensemble of CommunityForensics ViT + haywoodsloan SwinV2 + umm-maybe, chosen and
scored **leave-one-dataset-out** (fit on two public sets, test on the third):

| | Accuracy | AUC | ECE |
|---|---|---|---|
| Previous single model | ~60 % | 0.65 | uncalibrated |
| **Calibrated ensemble (held-out)** | **86.2 %** | **0.933** | **0.024** |
| held-out GenImage / CommunityForensics / WebArt | 96 % / 96 % / 66 % | | |

Field check (the images that previously returned "no clear answer"): AI portrait → **98.9 % AI**, AI illustration →
**99.9 % AI**, real press photo → **33 % AI (authentic)**; the IPTC-tagged AI PNG scores 48 % from pixels but is
caught at 92 % by its embedded generator metadata.

**Weak spot:** paintings/illustrations (WebArt 66 %). Photorealistic fakes, the kind used in fake news, are 96 %.

## 2. Face swaps and synthetic faces

**Data:** DeepFakeFace (real IMDB-WIKI faces vs InsightFace swaps and Stable-Diffusion-inpainted faces), 300 test samples.

| Detector | AUC | Acc | TPR | TNR |
|---|---|---|---|---|
| prithivMLmods/Deep-Fake-Detector-v2-Model (**previous**) | 0.508 | 48 % | 93 % | 3 % |
| dima806/deepfake_vs_real_image_detection | 0.508 | 51 % | 5 % | 98 % |
| prithivMLmods/AI-vs-Deepfake-vs-Real-Siglip2 | 0.461 | 49 % | 93 % | 5 % |
| haywoodsloan SwinV2 | 0.626 | 59 % | 21 % | 97 % |
| CommunityForensics ViT | 0.883 | 80 % | 60 % | 99 % |
| **Face-swap head on CommunityForensics features (shipped)** | **0.944** | **87.3 %** | **83 %** | **92 %** |

The head is a logistic layer trained on 1,800 images from the DeepFakeFace *train* split and scored on 600 from the
separate *test* split (`eval/train_face_head.py`). Per type: SD-inpainted faces 99 % caught, **InsightFace swaps 50 %**
(hardest), real faces 8 % false alarms. Both splits come from one dataset family, so real-world accuracy will be lower.

## 3. Cloned and synthetic voices

**Data:** In-the-Wild (real speech of celebrities/politicians vs deepfakes found online) and an ElevenLabs clone set; 300 each.

| Detector | In-the-Wild | ElevenLabs |
|---|---|---|
| MelodyMachine/Deepfake-audio-detection-V2 (**previous**) | 0.403 | 0.492 |
| **mo-thecreator/Deepfake-audio-detection** | **0.956** | 0.814 |
| **Gustking/wav2vec2-large-xlsr-deepfake-audio-classification** | 0.941 | **0.894** |
| Om-Parab/distilhubert-…-in-the-wild | 1.000\* | 0.911 |
| garystafford/wav2vec2-deepfake-voice-detector | 0.659 | 0.998\* |
| Hemgg/Deepfake-audio-detection | 0.775 | 0.453 |
| Vansh180/deepfake-audio-wav2vec2 | 0.489 | 0.184 |

**Shipped:** calibrated ensemble of mo-thecreator + Gustking XLSR. **Cross-dataset** (calibrated on one set, tested on
the other): **82.3 % accuracy, AUC 0.913** (In-the-Wild 84 % / 0.97, ElevenLabs 80 % / 0.90), ECE 0.055.
The sample case's Windows-TTS "dubbed" clip moved from undetected to **97 % synthetic voice**.

## 4. Image manipulation (editing, splicing, AI inpainting)

**Data:** 600 images from CASIA-style tampering benchmarks (IMD2020, HiFi-IFDL, CocoGlide, OpenSDID SD1.5/SDXL/Flux, TGIF Flux).

| Method | AUC | Acc | Notes |
|---|---|---|---|
| Classical forensics (ELA, noise residual, JPEG grid, copy-move) → calibrated logistic model | 0.671 | 64.8 % | ~chance on IMD2020 (0.54) and Flux inpainting (0.50) |
| Tile-scan for local AI edits | 0.614 | 76.9 % | catches ~3–6 % of AI inpainting at 1–2 % false alarms |
| TruFor (CVPR 2023) | *pending: weights installed, run `python -m eval.bench_trufor`* | | learned forgery detection + localisation |

**Honest conclusion:** textbook forensics (ELA etc.) are weak evidence on modern edits, so TruthLens now down-weights
them and only treats strong cues (confident clone matches, EXIF-thumbnail mismatch, recorded edit history) as proof
of manipulation. Learned forgery detection (TruFor) is the planned fix for local edits.

## 5. End-to-end verdict (what a judge sees)

Full image pipeline + threat matrix on 606 held-out images (GenImage, CommunityForensics, DeepFakeFace, field uploads),
excluding every image used for calibration. Letting unbenchmarked heuristics (ELA-based model, copy-move, tile scan)
decide the verdict gave **17.8 % false alarms on real photos**; the classical model fired on 15 % of real *and* 17 % of
fake images. Rule now: **only calibrated detectors decide the verdict**; heuristics stay as supporting evidence.

| Verdict rule | Accuracy | False alarms on real | Fakes caught |
|---|---|---|---|
| Heuristics allowed to decide | 87.0 % | 17.8 % | 92.1 % |
| **Calibrated detectors only (cut-off 0.6)** | **92.4 %** | **1.0 %** | 85.2 % |

Also fixed after field testing: Haar face detector boxing textures as faces (replaced by OpenCV YuNet), copy-move
matching periodic patterns (window grilles), music triggering speech-only checks.

## 6. Robustness: stripped metadata and laundering

300 held-out images (130 AI, 170 real), AI-image verdict at cut-off 0.6, original calibration → hardened calibration
(refit on originals + laundered copies with image-quality features, `eval/harden_ai.py`):

| Attack | Accuracy | AI caught | False alarms on real |
|---|---|---|---|
| none | 95.7 → 95.3 % | 93 → 92 % | 2 → 2 % |
| **metadata stripped** | **95.7 → 95.3 %** | **93 → 92 %** | 2 → 2 % |
| screenshot (crop + PNG) | 96.3 → 95.3 % | 94 → 92 % | 2 → 2 % |
| downscaled 50 % | 91.7 → 91.7 % | 85 → 85 % | 3 → 4 % |
| WhatsApp-style (1600 px, JPEG 75) | 88.7 → 90.0 % | 75 → 78 % | 1 → 1 % |
| blur | 87.7 → **91.0 %** | 98 → 96 % | **20 → 13 %** |
| heavy JPEG (q 50) | 79.7 → 81.7 % | 53 → 58 % | 0 → 1 % |
| noise (σ 6) | 85.0 → 85.3 % | 68 → 69 % | 2 → 2 % |
| all combined | 78.3 → 79.0 % | 52 → 54 % | 2 → 2 % |

**Takeaways:** removing digital signatures (metadata, C2PA, screenshots) has no effect, because detection reads
generator fingerprints in the pixels. Deliberate laundering (heavy compression + noise) weakens those fingerprints;
recalibration recovers only a little, since it cannot restore destroyed signal. The real fix is fine-tuning the
backbone with laundering augmentation (future work).

## 7. What is *not* measured yet
* Lip-sync / reenactment deepfakes (no public benchmark run yet); the lip-sync check is a signal-processing method.
* AI-generated **video** uses the image ensemble on sampled frames; not yet benchmarked on generated-video datasets.
* Context checks (quotes vs transcript, dates vs metadata) are deterministic rules; accuracy depends on Whisper transcription.

## Reproduce
```powershell
cd backend
.venv\Scripts\python -m eval.bench_ai_images 400
.venv\Scripts\python -m eval.stack_ai
.venv\Scripts\python -m eval.bench_faces_audio all 300
.venv\Scripts\python -m eval.train_face_head
.venv\Scripts\python -m eval.stack_voice
.venv\Scripts\python -m eval.bench_manip 600
.venv\Scripts\python -m eval.bench_hidden_ai
```
Benchmark data (~4 GB) is cached in `%LOCALAPPDATA%\truthlens\eval-data`, outside the project folder.
