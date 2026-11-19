"""Build synthetic test evidence in ../samples (run with the backend venv python).

- photo_original.jpg : synthetic 'camera' scene (textured, noisy), single JPEG compression
- photo_tampered.jpg : same scene with (a) a patch pasted from a heavily-compressed source and
                       (b) a cloned (copy-move) region, then re-saved
- tts_spliced.wav    : Windows TTS speech with a mid-recording digital-silence splice and a noise-floor jump
- dubbed_clip.mp4    : still image + TTS audio (no lip movement) -> sync check should flag it
- caption.txt        : claim text with a quote that is NOT in the audio and a date
"""
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter

import imageio_ffmpeg

OUT = Path(__file__).resolve().parents[2] / "samples"
OUT.mkdir(exist_ok=True)
rng = np.random.default_rng(7)

# ---------------------------------------------------------------- image
W, H = 1280, 860
y, x = np.mgrid[0:H, 0:W]
base = np.stack([90 + 80 * np.sin(x / 140) + 40 * (y / H), 120 + 60 * np.cos(y / 90), 150 - 50 * (x / W)], -1)
img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
d = ImageDraw.Draw(img)
for _ in range(60):
    cx, cy, r = rng.integers(0, W), rng.integers(0, H), rng.integers(10, 70)
    col = tuple(int(v) for v in rng.integers(30, 230, 3))
    (d.ellipse if rng.random() < .5 else d.rectangle)([cx - r, cy - r, cx + r, cy + r], fill=col)
img = img.filter(ImageFilter.GaussianBlur(1.2))
arr = np.asarray(img).astype(np.float32) + rng.normal(0, 6, (H, W, 3))  # sensor-like noise
img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
img.save(OUT / "photo_original.jpg", quality=92)

t = Image.open(OUT / "photo_original.jpg").convert("RGB")
# (a) splice: a smooth, noise-free patch that went through low-quality JPEG
patch = Image.new("RGB", (260, 200), (220, 60, 50))
pd = ImageDraw.Draw(patch)
pd.ellipse([30, 20, 230, 180], fill=(250, 220, 40))
pd.text((80, 90), "FAKE", fill=(0, 0, 0))
buf = io.BytesIO(); patch.save(buf, "JPEG", quality=35); buf.seek(0)
t.paste(Image.open(buf), (820, 520))
# (b) copy-move: clone a textured block elsewhere
blk = t.crop((150, 120, 390, 330))
t.paste(blk, (520, 80))
t.save(OUT / "photo_tampered.jpg", quality=88)

# ---------------------------------------------------------------- audio
TTS_TEXT = ("Good evening everyone. Today I want to talk about the new water project in our city. We have completed "
            "the first phase on time and within budget. The second phase will begin next month, and we expect it to "
            "bring clean water to forty thousand homes. Thank you for your continued support.")
if not (OUT / "tts_speech.wav").exists():
    if sys.platform != "win32":
        sys.exit("samples/tts_speech.wav missing: record or synthesise ~20 s of speech there and re-run.")
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{OUT / 'tts_speech.wav'}'); $s.Speak('{TTS_TEXT}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
speech, sr = sf.read(OUT / "tts_speech.wav")
if speech.ndim > 1:
    speech = speech.mean(1)
speech = speech / (np.abs(speech).max() + 1e-9) * 0.6
room = rng.normal(0, 0.004, len(speech))
cut = int(len(speech) * 0.45)
noisy_tail = speech[cut:] + rng.normal(0, 0.03, len(speech) - cut)  # different 'room' after splice
spliced = np.concatenate([speech[:cut] + room[:cut], np.zeros(int(0.4 * sr)), noisy_tail])
sf.write(OUT / "tts_spliced.wav", spliced.astype(np.float32), sr)

# ---------------------------------------------------------------- video (still frame + TTS = no lip motion)
ff = imageio_ffmpeg.get_ffmpeg_exe()
subprocess.run([ff, "-y", "-loop", "1", "-i", str(OUT / "photo_original.jpg"), "-i", str(OUT / "tts_speech.wav"),
                "-vf", "scale=1280:860,format=yuv420p", "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
                "-shortest", str(OUT / "dubbed_clip.mp4")], check=True, capture_output=True)

(OUT / "caption.txt").write_text(
    'BREAKING!!! LEAKED clip from today: the mayor admits "the water project was a complete failure and the money is gone". '
    "Recorded at the city hall press event, March 2019. Share before it is deleted!", encoding="utf-8")
print("samples written to", OUT)
for p in sorted(OUT.iterdir()):
    print(f"  {p.name:22s} {p.stat().st_size:>10,d} B")
