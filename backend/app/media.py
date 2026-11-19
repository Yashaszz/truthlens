"""FFmpeg helpers (uses the ffmpeg binary bundled with imageio-ffmpeg, no system install needed)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def _run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run([FFMPEG, "-hide_banner", *args], capture_output=True, text=True,
                          errors="replace", timeout=timeout, creationflags=_NO_WINDOW)


def probe(path: Path) -> dict:
    """Parse `ffmpeg -i` output into container/stream info and metadata tags."""
    err = _run(["-i", str(path)], timeout=60).stderr
    info: dict = {"duration": None, "video": None, "audio": None, "tags": {}, "raw": err[-4000:]}
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    vm = re.search(r"Stream #\S+.*?Video:\s*([^\s,]+)(.*)", err)
    if vm:
        rest = vm[2]
        res = re.search(r"(\d{2,5})x(\d{2,5})", rest)
        fps = re.search(r"([\d.]+)\s*fps", rest)
        info["video"] = {"codec": vm[1], "width": int(res[1]) if res else None,
                         "height": int(res[2]) if res else None,
                         "fps": float(fps[1]) if fps else None}
    am = re.search(r"Stream #\S+.*?Audio:\s*([^\s,]+)(.*)", err)
    if am:
        sr = re.search(r"(\d+)\s*Hz", am[2])
        info["audio"] = {"codec": am[1], "sample_rate": int(sr[1]) if sr else None,
                         "channels": "stereo" if "stereo" in am[2] else ("mono" if "mono" in am[2] else None)}
    for key in ("creation_time", "encoder", "major_brand", "handler_name", "com.apple.quicktime.make",
                "com.apple.quicktime.model", "com.apple.quicktime.software", "location", "comment", "title"):
        tm = re.search(rf"^\s*{re.escape(key)}\s*:\s*(.+)$", err, re.MULTILINE)
        if tm:
            info["tags"][key] = tm[1].strip()
    return info


def to_wav(src: Path, dst: Path, sr: int = 16000, max_seconds: float | None = None) -> bool:
    args = ["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr)]
    if max_seconds:
        args += ["-t", str(max_seconds)]
    args += ["-f", "wav", str(dst)]
    r = _run(args)
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 1000


def to_wav_native(src: Path, dst: Path, max_seconds: float | None = None) -> bool:
    """Mono WAV at the source's native sample rate (for bandwidth analysis)."""
    args = ["-y", "-i", str(src), "-vn", "-ac", "1"]
    if max_seconds:
        args += ["-t", str(max_seconds)]
    args += ["-f", "wav", str(dst)]
    r = _run(args)
    return r.returncode == 0 and dst.exists()


def to_browser_mp4(src: Path, dst: Path) -> bool:
    """Make a browser-playable H.264 preview copy (original evidence is never modified)."""
    r = _run(["-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
              "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)])
    return r.returncode == 0 and dst.exists()


def to_browser_audio(src: Path, dst: Path) -> bool:
    r = _run(["-y", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "160k", str(dst)])
    return r.returncode == 0 and dst.exists()
