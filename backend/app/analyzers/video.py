"""Video forensics: frame sampling, face deepfake scoring, temporal consistency, container metadata.
Also produces the mouth-motion series used by the audio-visual sync check."""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .. import media, models
from ..common import AnalysisContext, clamp, fmt_ts
from ..config import VIDEO_MAX_SAMPLES, VIDEO_MAX_SECONDS, VIDEO_SAMPLE_FPS
from . import forensics as fx
from .image import analyze_image

EDITOR_TAGS = ["premiere", "after effects", "capcut", "davinci", "final cut", "imovie", "handbrake", "filmora",
               "kinemaster", "inshot", "vn video", "clipchamp", "deepfacelab", "faceswap", "lavf", "lavc"]


def analyze_video(ctx: AnalysisContext, ev: dict, path: Path) -> dict:
    eid = ev["id"]
    info = media.probe(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        ctx.limit(f"{eid}: video could not be decoded by OpenCV.")
        return {"probe": info, "error": "decode failed"}
    fps = cap.get(cv2.CAP_PROP_FPS) or (info.get("video") or {}).get("fps") or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = info.get("duration") or (total / fps if total else 0)
    max_frames = int(min(total or 10**9, VIDEO_MAX_SECONDS * fps))
    if duration and duration > VIDEO_MAX_SECONDS:
        ctx.limit(f"{eid}: only the first {VIDEO_MAX_SECONDS}s of {duration:.0f}s were analysed.")
    n_samples = int(min(VIDEO_MAX_SAMPLES, max(8, (max_frames / fps) * VIDEO_SAMPLE_FPS)))
    sample_idx = set(np.linspace(0, max(0, max_frames - 1), n_samples).astype(int).tolist())

    hist_diff, mouth_motion, sharp_ratio = [], [], []
    samples = []  # dicts: idx, t, frame (bgr downscaled), face box
    prev_hist = prev_mouth = None
    face_box = None
    i = 0
    while i < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        h0, w0 = frame.shape[:2]
        scale = 360 / max(h0, w0) if max(h0, w0) > 360 else 1.0
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([g], [0], None, [64], [0, 256]).ravel()
        hist /= hist.sum() + 1e-9
        hist_diff.append(0.0 if prev_hist is None else float(0.5 * np.abs(hist - prev_hist).sum()))
        prev_hist = hist
        # face tracking (re-detect every 5 frames)
        if i % 5 == 0 or face_box is None:
            faces = fx.detect_faces(g, min_frac=0.08)
            face_box = faces[0] if faces else None
        if face_box is not None:
            x, y, fw, fh = face_box
            my0, my1 = y + int(fh * 0.62), y + fh
            mx0, mx1 = x + int(fw * 0.2), x + int(fw * 0.8)
            mouth = g[my0:my1, mx0:mx1]
            mouth = cv2.resize(mouth, (48, 24)).astype(np.float32) if mouth.size else None
            if mouth is not None and prev_mouth is not None:
                mouth_motion.append(float(np.abs(mouth - prev_mouth).mean()))
            else:
                mouth_motion.append(np.nan)
            prev_mouth = mouth
        else:
            mouth_motion.append(np.nan)
            prev_mouth = None
        if i in sample_idx:
            fs = 720 / max(h0, w0) if max(h0, w0) > 720 else 1.0
            big = cv2.resize(frame, None, fx=fs, fy=fs) if fs < 1 else frame.copy()
            box = None
            if face_box is not None:
                box = tuple(int(v / scale * fs) for v in face_box)
            samples.append({"idx": i, "t": i / fps, "frame": big, "box": box})
        i += 1
    cap.release()
    n_read = i
    t_axis = np.arange(n_read) / fps

    summary: dict = {"probe": {k: v for k, v in info.items() if k != "raw"}, "fps": round(fps, 3),
                     "frames": n_read, "duration": round(duration or n_read / fps, 2),
                     "samples": len(samples), "artifacts": {}}

    # ---------------- face deepfake model over sampled frames -------------------
    crops, crop_samples = [], []
    for s in samples:
        if s["box"] is None:
            continue
        h, w = s["frame"].shape[:2]
        x0, y0, x1, y1 = fx.expand_box(s["box"], w, h)
        crop = s["frame"][y0:y1, x0:x1]
        if crop.size == 0 or min(crop.shape[:2]) < 40:
            continue
        crops.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
        crop_samples.append(s)
        # face vs surrounding sharpness (blending indicator)
        gface = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        fx0, fy0, fw, fh = s["box"]
        ring = cv2.cvtColor(s["frame"][max(0, fy0 - fh // 2):min(h, fy0 + fh + fh // 2),
                                       max(0, fx0 - fw // 2):min(w, fx0 + fw + fw // 2)], cv2.COLOR_BGR2GRAY)
        r = fx.sharpness(gface) / (fx.sharpness(ring) + 1e-6)
        s["sharp_ratio"] = r
        sharp_ratio.append(r)
    summary["face_frames"] = len(crops)
    timeline = []
    probs = models.face_deepfake_probs(crops) if crops else []
    if crops and probs is None:
        ctx.limit(f"Face deepfake model unavailable ({models.model_error('face_deepfake')}).")
        probs = []
    for s, p in zip(crop_samples, probs or []):
        s["p_fake"] = p
    for s in samples:
        timeline.append({"t": round(s["t"], 2), "frame": s["idx"], "p_fake": round(s.get("p_fake", np.nan), 4)
                         if "p_fake" in s else None, "face": s["box"] is not None,
                         "sharp_ratio": round(s.get("sharp_ratio", 0), 3) if "sharp_ratio" in s else None})
    summary["frame_timeline"] = timeline
    if not crops:
        ctx.limit(f"{eid}: no clear frontal face found in sampled frames; face-manipulation analysis not possible.")

    if probs:
        arr = np.array(probs)
        agg = float(0.5 * np.median(arr) + 0.5 * np.percentile(arr, 80))
        flagged = [s for s in crop_samples if s.get("p_fake", 0) >= 0.65]
        flagged.sort(key=lambda s: -s["p_fake"])
        thumbs = []
        for s in flagged[:6]:
            vis = s["frame"].copy()
            x, y, bw, bh = s["box"]
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 0, 255), 3)
            cv2.putText(vis, f"{fmt_ts(s['t'])}  P(fake)={s['p_fake']:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 0, 255), 2)
            p, url = ctx.artifact_path(eid, f"frame_{s['idx']:06d}.jpg")
            cv2.imwrite(str(p), vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
            s["thumb"] = url
            thumbs.append(url)
        rel = 0.5 * min(1.0, len(crops) / 10)  # fewer usable faces -> less reliable
        stability = float(arr.std())
        if flagged:
            f = ctx.finding("video", eid, "face-manipulation",
                            f"Face manipulation indicators in {len(flagged)}/{len(crops)} sampled frames",
                            f"The ViT deepfake classifier ({models.MODELS['face_deepfake']}) scored faces in "
                            f"{len(flagged)} of {len(crops)} sampled frames at ≥65% (median {np.median(arr):.0%}, "
                            f"peak {arr.max():.0%}, frame-to-frame SD {stability:.2f}).",
                            {"type": "frames", "frames": [{"t": round(s["t"], 2), "frame": s["idx"],
                                                           "score": round(s["p_fake"], 3), "bbox": list(s["box"]),
                                                           "thumb": s.get("thumb")} for s in flagged]},
                            agg, rel, "face_deepfake_model", thumbs,
                            limitations="Single-frame classifier; compression, motion blur and low face resolution "
                                        "raise false-positive rates. Does not model temporal artefacts.",
                            alternatives=["Video beauty filter / face smoothing", "Heavy re-compression by platform"])
            ctx.signal("face_deepfake_model", "video", eid, agg, rel,
                       f"Aggregated P(deepfake) = {agg:.2f} over {len(crops)} face frames.", [f["id"]],
                       label="Face deepfake classifier (ViT)")
        else:
            ctx.signal("face_deepfake_model", "video", eid, agg, rel,
                       f"Aggregated P(deepfake) = {agg:.2f} over {len(crops)} face frames; none above 0.65.",
                       label="Face deepfake classifier (ViT)")
        if stability > 0.25 and len(arr) >= 6:
            f = ctx.finding("video", eid, "temporal", "Unstable face authenticity across frames",
                            f"Classifier output swings strongly between frames (SD {stability:.2f}). Face swaps "
                            "often fail intermittently (pose changes, occlusion), giving flickering scores.",
                            {"type": "series", "series": "frame_timeline"}, clamp(0.3 + stability), 0.3,
                            "face_deepfake_model", alternatives=["Changing pose/lighting", "Multiple people"])

    # ---------------- face sharpness (blending boundary) ------------------------
    if len(sharp_ratio) >= 5:
        med = float(np.median(sharp_ratio))
        summary["face_sharpness_ratio"] = round(med, 3)
        if med < 0.45:
            f = ctx.finding("video", eid, "face-manipulation", "Face region blurrier than its surroundings",
                            f"Median face/surround sharpness ratio is {med:.2f}. Face-swap pipelines blend a "
                            "generated face at lower resolution, leaving it softer than hair/background.",
                            {"type": "series", "series": "frame_timeline"}, clamp(0.35 + (0.45 - med)), 0.35,
                            "face_sharpness", alternatives=["Shallow depth of field focused elsewhere",
                                                            "Skin-smoothing filter", "Motion blur"])
            ctx.signal("face_sharpness", "video", eid, clamp(0.35 + (0.45 - med)), 0.35,
                       f"Face/surround sharpness ratio {med:.2f}.", [f["id"]], label="Face blending sharpness")
        else:
            ctx.signal("face_sharpness", "video", eid, 0.2, 0.3, f"Face/surround sharpness ratio {med:.2f} (normal).",
                       label="Face blending sharpness")

    # ---------------- temporal: cuts & frozen frames ----------------------------
    hd = np.array(hist_diff)
    cuts = []
    if len(hd) > 10:
        z = fx.robust_z(hd)
        cand = np.where((z > 8) & (hd > 0.25))[0]
        last = -999
        for c in cand:
            if c - last > fps * 0.5:
                cuts.append(int(c))
            last = c
    frozen = []
    if len(hd) > 10:
        still = hd < 0.0015
        run_start = None
        for k, v in enumerate(np.append(still, False)):
            if v and run_start is None:
                run_start = k
            elif not v and run_start is not None:
                if k - run_start >= max(3, int(fps * 0.3)):
                    frozen.append((run_start, k))
                run_start = None
    summary["cuts"] = [{"t": round(c / fps, 2), "frame": c} for c in cuts]
    summary["frozen"] = [{"start": round(a / fps, 2), "end": round(b / fps, 2)} for a, b in frozen]
    if cuts:
        cps = len(cuts) / max(1.0, n_read / fps) * 60
        s = clamp(0.25 + 0.05 * min(len(cuts), 6), 0.25, 0.55)
        f = ctx.finding("video", eid, "temporal", f"{len(cuts)} abrupt scene transition(s)",
                        f"Sharp histogram discontinuities at {', '.join(fmt_ts(c / fps) for c in cuts[:8])}. "
                        "In footage presented as a single continuous recording, hard cuts indicate splicing.",
                        {"type": "timestamps", "times": [round(c / fps, 2) for c in cuts]}, s, 0.3, "temporal_cuts",
                        limitations="Normal for edited news/social video; only meaningful if the clip is claimed to be unedited.",
                        alternatives=["Ordinary editing", "Camera flash or lighting change"])
        ctx.signal("temporal_cuts", "video", eid, s, 0.3, f"{len(cuts)} cuts ({cps:.1f}/min).", [f["id"]],
                   label="Temporal discontinuities")
    else:
        ctx.signal("temporal_cuts", "video", eid, 0.15, 0.3, "No abrupt discontinuities; temporally continuous.",
                   label="Temporal discontinuities")
    if frozen:
        f = ctx.finding("video", eid, "temporal", f"{len(frozen)} frozen/duplicated frame run(s)",
                        "Consecutive near-identical frames at " + ", ".join(f"{fmt_ts(a / fps)}–{fmt_ts(b / fps)}" for a, b in frozen[:6])
                        + ". Duplicated frames can hide removed content or mark an insertion point.",
                        {"type": "segments", "segments": [{"start": round(a / fps, 2), "end": round(b / fps, 2)} for a, b in frozen]},
                        0.4, 0.35, "frozen_frames", alternatives=["Static scene", "Variable-frame-rate encoding"])
        ctx.signal("frozen_frames", "video", eid, 0.4, 0.35, f"{len(frozen)} frozen runs.", [f["id"]],
                   label="Frozen/duplicated frames")

    # ---------------- container metadata ----------------------------------------
    tags = info.get("tags", {})
    blob = " ".join(tags.values()).lower()
    editors = [e for e in EDITOR_TAGS if e in blob]
    if editors:
        reenc = [e for e in editors if e in ("lavf", "lavc", "handbrake")]
        named = [e for e in editors if e not in reenc]
        s = 0.45 if named else 0.3
        f = ctx.finding("video", eid, "metadata", "Container written by editing/re-encoding software",
                        f"Container tags reference: {', '.join(tags.get(k, '') for k in ('encoder', 'handler_name', 'com.apple.quicktime.software') if tags.get(k))}. "
                        "The file is not a camera original.",
                        {"type": "metadata", "fields": list(tags.keys())}, s, 0.35, "video_container",
                        alternatives=["Platform transcoding on upload/download", "Trimmed for sharing"])
        ctx.signal("video_container", "video", eid, s, 0.35, f"Encoder tags: {', '.join(editors)}", [f["id"]],
                   label="Container metadata")
    elif tags.get("com.apple.quicktime.make") or tags.get("com.apple.quicktime.model"):
        ctx.signal("video_container", "video", eid, 0.15, 0.4, "Camera make/model present in container.",
                   label="Container metadata")
    summary["creation_time"] = tags.get("creation_time")

    # ---------------- ELA on the most suspicious frame --------------------------
    key = max(crop_samples, key=lambda s: s.get("p_fake", 0)) if crop_samples else (samples[len(samples) // 2] if samples else None)
    if key is not None:
        kp = ctx.work_dir / f"{eid}_keyframe.png"
        cv2.imwrite(str(kp), key["frame"])
        before = len(ctx.findings)
        analyze_image(ctx, ev, kp, source_label=f"keyframe_{key['idx']}", modality="video", lightweight=True)
        for f in ctx.findings[before:]:
            f["location"] = {"type": "frames", "frames": [{"t": round(key["t"], 2), "frame": key["idx"]}],
                             "regions": f["location"].get("regions"), "width": f["location"].get("width"),
                             "height": f["location"].get("height")}
            f["title"] = f"Keyframe {fmt_ts(key['t'])}: " + f["title"]
        summary["artifacts"]["keyframe_ela"] = f"artifacts/{eid}/keyframe_{key['idx']}_ela.jpg"
        summary["keyframe_t"] = round(key["t"], 2)

    # sync inputs & frame hashes for cross-modal matching
    mm = np.array(mouth_motion, dtype=np.float64)
    summary["_mouth_motion"] = mm
    summary["_fps"] = fps
    summary["_hashes"] = [(s["t"], fx.dhash(cv2.cvtColor(s["frame"], cv2.COLOR_BGR2GRAY))) for s in samples]
    summary["has_audio"] = info.get("audio") is not None
    return summary
