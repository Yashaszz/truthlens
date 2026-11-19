"""Image authenticity analysis: metadata, ELA, noise residual, JPEG grid, copy-move, pretrained models."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageOps

from .. import models
from ..common import AnalysisContext, clamp
from . import forensics as fx

EDIT_SOFTWARE = ["photoshop", "gimp", "lightroom", "snapseed", "picsart", "canva", "affinity", "pixlr",
                 "facetune", "paint.net", "faceapp", "remini", "photopea", "meitu", "airbrush", "luminar"]
AI_MARKERS = {
    b"Stable Diffusion": "Stable Diffusion", b"stable-diffusion": "Stable Diffusion",
    b"sd-metadata": "Stable Diffusion (InvokeAI)", b"ComfyUI": "ComfyUI", b"Midjourney": "Midjourney",
    b"DALL-E": "DALL-E", b"DALL\xc2\xb7E": "DALL-E", b"Adobe Firefly": "Adobe Firefly",
    b"NovelAI": "NovelAI", b"Negative prompt:": "Diffusion prompt parameters",
    b"trainedAlgorithmicMedia": "IPTC 'trained algorithmic media' (AI-generated) flag",
    b"compositeWithTrainedAlgorithmicMedia": "IPTC 'composite with AI' flag",
    b"Google AI": "Google generative AI", b"Imagen": "Imagen",
}


def _exif(pil: Image.Image) -> dict:
    out = {}
    try:
        ex = pil.getexif()
        for k, v in ex.items():
            out[ExifTags.TAGS.get(k, str(k))] = v
        for ifd_id in (0x8769, 0x8825):  # Exif IFD, GPS IFD
            try:
                sub = ex.get_ifd(ifd_id)
            except Exception:
                sub = {}
            for k, v in sub.items():
                name = (ExifTags.GPSTAGS if ifd_id == 0x8825 else ExifTags.TAGS).get(k, str(k))
                out[("GPS." if ifd_id == 0x8825 else "") + name] = v
    except Exception:
        pass
    clean = {}
    for k, v in out.items():
        if isinstance(v, bytes):
            v = v[:64].decode("latin-1", "replace")
        if isinstance(v, (tuple, list)):
            v = [float(x) if hasattr(x, "numerator") else x for x in v]
        elif hasattr(v, "numerator"):
            v = float(v)
        s = str(v)
        if len(s) <= 200 and k not in ("MakerNote", "PrintImageMatching", "UserComment", "ComponentsConfiguration"):
            clean[k] = v if isinstance(v, (int, float, list)) else s
    return clean


def _parse_exif_dt(s) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(s).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def _gps(exif: dict) -> dict | None:
    try:
        def conv(v, ref):
            d, m, s = [float(x) for x in v]
            val = d + m / 60 + s / 3600
            return -val if str(ref).upper() in ("S", "W") else val
        return {"lat": round(conv(exif["GPS.GPSLatitude"], exif.get("GPS.GPSLatitudeRef", "N")), 6),
                "lon": round(conv(exif["GPS.GPSLongitude"], exif.get("GPS.GPSLongitudeRef", "E")), 6)}
    except Exception:
        return None


def analyze_image(ctx: AnalysisContext, ev: dict, path: Path, *, source_label: str = "image",
                  modality: str = "image", lightweight: bool = False) -> dict:
    eid = ev["id"]
    raw = path.read_bytes()
    pil = Image.open(path)
    fmt = (pil.format or path.suffix.strip(".")).upper()
    pil = ImageOps.exif_transpose(pil) if not lightweight else pil
    rgb = pil.convert("RGB")
    bgr = fx.to_bgr(rgb)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    is_jpeg = fmt in ("JPEG", "JPG", "MPO")
    summary: dict = {"format": fmt, "width": w, "height": h, "mode": pil.mode}

    # ---------------- metadata -------------------------------------------------
    if not lightweight:
        exif = _exif(pil)
        summary["exif"] = exif
        info_text = {k: str(v)[:300] for k, v in (pil.info or {}).items() if isinstance(v, (str, bytes))
                     and k not in ("icc_profile", "exif")}
        summary["embedded_text"] = info_text
        try:
            summary["jpeg_quality_tables"] = len(pil.quantization) if is_jpeg and hasattr(pil, "quantization") else None
        except Exception:
            pass

        hits = sorted({name for marker, name in AI_MARKERS.items() if marker in raw[:4_000_000]})
        if "parameters" in info_text or "prompt" in info_text or "workflow" in info_text:
            hits.append("PNG text chunk with generation parameters")
        has_c2pa = b"c2pa" in raw[:4_000_000] or b"jumb" in raw[:200_000]
        summary["c2pa_manifest"] = has_c2pa
        if hits:
            f = ctx.finding(modality, eid, "synthetic-generation", "Generator metadata embedded in file",
                            "The file contains metadata written by generative-AI software: " + ", ".join(hits)
                            + ". This is direct provenance evidence, unlike statistical detector scores.",
                            {"type": "metadata", "fields": hits}, 0.92, 0.85, "generator_metadata",
                            limitations="Metadata can be added or copied deliberately; its absence proves nothing.",
                            alternatives=["Image legitimately produced/edited with AI tools and disclosed as such"])
            ctx.signal("generator_metadata", modality, eid, 0.92, 0.85,
                       "Generative-AI software markers present in file metadata.", [f["id"]],
                       label="Generator metadata")
        else:
            ctx.signal("generator_metadata", modality, eid, 0.3, 0.05,
                       "No generator markers found (weak evidence: metadata is easily stripped).",
                       label="Generator metadata")

        software = str(exif.get("Software", "")) + " " + str(exif.get("ProcessingSoftware", ""))
        edit_hits = [s for s in EDIT_SOFTWARE if s in software.lower()]
        if edit_hits:
            f = ctx.finding(modality, eid, "editing", f"Editing software recorded: {software.strip()}",
                            "EXIF 'Software' tag names an image editor, so the file was saved by editing software "
                            "after capture.", {"type": "metadata", "fields": ["EXIF.Software"]}, 0.55, 0.6,
                            "exif_software", limitations="Routine adjustments (crop, exposure) also set this tag.",
                            alternatives=["Benign colour/crop adjustment", "Export from a photo library app"])
            ctx.signal("exif_software", modality, eid, 0.55, 0.6, f"Editor recorded: {software.strip()}",
                       [f["id"]], label="EXIF software tag")
        elif exif.get("Software"):
            ctx.signal("exif_software", modality, eid, 0.25, 0.35,
                       f"Software tag '{exif.get('Software')}' is not a known editor (camera firmware/OS).",
                       label="EXIF software tag")

        cam = exif.get("Make") or exif.get("Model")
        if is_jpeg and not exif:
            f = ctx.finding(modality, eid, "metadata", "No EXIF metadata",
                            "The JPEG carries no camera metadata. Messaging/social platforms strip EXIF routinely, "
                            "so this mainly removes the ability to verify capture device and time.",
                            {"type": "metadata", "fields": ["EXIF"]}, 0.35, 0.25, "exif_missing",
                            alternatives=["Downloaded from social media / messaging app", "Screenshot"])
            ctx.signal("exif_missing", modality, eid, 0.35, 0.25, "EXIF absent.", [f["id"]], label="EXIF presence")
        elif cam:
            ctx.signal("exif_missing", modality, eid, 0.2, 0.3, f"Camera metadata present ({cam}).",
                       label="EXIF presence")
        d_orig = _parse_exif_dt(exif.get("DateTimeOriginal"))
        d_mod = _parse_exif_dt(exif.get("DateTime"))
        summary["capture_time"] = d_orig.isoformat() if d_orig else None
        summary["modify_time"] = d_mod.isoformat() if d_mod else None
        if d_orig and d_mod and abs((d_mod - d_orig).total_seconds()) > 120:
            gap = d_mod - d_orig
            f = ctx.finding(modality, eid, "metadata", "Modification time differs from capture time",
                            f"DateTimeOriginal {d_orig} vs DateTime {d_mod} (gap {gap}). The file was re-saved after capture.",
                            {"type": "metadata", "fields": ["EXIF.DateTimeOriginal", "EXIF.DateTime"]},
                            0.45, 0.45, "exif_dates", alternatives=["Later export or rotation in a gallery app"])
            ctx.signal("exif_dates", modality, eid, 0.45, 0.45, "Capture/modify timestamps disagree.", [f["id"]],
                       label="EXIF timestamps")
        elif d_orig and d_mod:
            ctx.signal("exif_dates", modality, eid, 0.2, 0.35, "Capture and modify timestamps agree.",
                       label="EXIF timestamps")
        summary["gps"] = _gps(exif)
        summary["camera"] = " ".join(str(x) for x in (exif.get("Make"), exif.get("Model")) if x) or None

    # ---------------- ELA (texture-normalised) ---------------------------------
    B = 16 if max(h, w) > 600 else 8
    ela = fx.ela_map(rgb)
    tex = fx.texture_map(gray)
    ela_b = fx.block_mean(ela, B)
    tex_b = fx.block_mean(tex, B)
    z = fx.texture_normalised_z(ela_b, tex_b)
    regions = fx.outlier_regions(z, B, thresh=4.0, min_blocks=4)
    ela_rel = (0.28 if is_jpeg else 0.2) * (0.6 if lightweight else 1.0) * (0.7 if max(h, w) < 400 else 1.0)  # benchmark AUC≈0.67
    out_p, out_url = ctx.artifact_path(eid, f"{source_label}_ela.jpg")
    cv2.imwrite(str(out_p), fx.heat_overlay(bgr, ela, regions), [cv2.IMWRITE_JPEG_QUALITY, 88])
    summary.setdefault("artifacts", {})["ela"] = out_url
    if regions:
        top = regions[0]
        s = clamp(0.3 + 0.05 * (top["mean_z"] - 4) + min(0.2, top["area_frac"] * 3), 0.3, 0.88)
        f = ctx.finding(modality, eid, "compositing", f"Compression-level anomaly ({len(regions)} region(s))",
                        f"Error Level Analysis found {len(regions)} region(s) whose recompression error is "
                        f"{top['mean_z']:.1f} robust SDs above what their texture predicts. Pasted or retouched "
                        "content often carries a different compression history than its surroundings.",
                        {"type": "regions", "regions": [{"bbox": r["bbox"], "label": f"R{i + 1}", "z": round(r['mean_z'], 1)}
                                                        for i, r in enumerate(regions)], "width": w, "height": h},
                        s, ela_rel, "ela", [out_url],
                        limitations="ELA is sensitive to resaving, resizing and strong texture; PNG/never-compressed "
                                    "images give weaker evidence.",
                        alternatives=["Local sharpening or noise reduction", "Text/graphics overlays",
                                      "Highly saturated or high-contrast edges"])
        ctx.signal("ela", modality, eid, s, ela_rel, f"{len(regions)} ELA outlier region(s), top z={top['mean_z']:.1f}.",
                   [f["id"]], label="Error level analysis")
    else:
        ctx.signal("ela", modality, eid, 0.15, ela_rel, "Compression error is consistent across the image.",
                   label="Error level analysis")

    # ---------------- noise residual consistency -------------------------------
    if not lightweight:
        gf = gray.astype(np.float32)
        resid = gf - cv2.medianBlur(gray, 3).astype(np.float32)
        NB = 32 if max(h, w) > 900 else 16
        nstd = np.log(fx.block_std(resid, NB) + 0.5)
        ntex = fx.block_mean(tex, NB)
        nz = fx.texture_normalised_z(nstd, ntex)
        nregions = fx.outlier_regions(nz, NB, thresh=3.8, min_blocks=3, two_sided=True)
        out_p, nurl = ctx.artifact_path(eid, f"{source_label}_noise.jpg")
        cv2.imwrite(str(out_p), fx.heat_overlay(bgr, np.abs(nz), nregions, color=(255, 200, 0)),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        summary["artifacts"]["noise"] = nurl
        nrel = 0.25 if max(h, w) >= 400 else 0.18  # benchmark AUC≈0.67
        if nregions:
            top = nregions[0]
            s = clamp(0.3 + 0.04 * (top["mean_z"] - 3.8) + min(0.15, top["area_frac"] * 2), 0.3, 0.8)
            f = ctx.finding(modality, eid, "compositing", f"Sensor-noise inconsistency ({len(nregions)} region(s))",
                            "The high-frequency noise residual in these regions differs strongly from the rest of "
                            "the image. Content from another camera, AI inpainting or heavy smoothing changes the "
                            "noise fingerprint.",
                            {"type": "regions", "regions": [{"bbox": r["bbox"], "label": f"N{i + 1}", "z": round(r['mean_z'], 1)}
                                                            for i, r in enumerate(nregions)], "width": w, "height": h},
                            s, nrel, "noise_residual", [nurl],
                            limitations="Out-of-focus areas, sky and skin smoothing filters also change noise levels.",
                            alternatives=["Depth-of-field blur", "Beauty/skin-smoothing filter", "Saturated highlights"])
            ctx.signal("noise_residual", modality, eid, s, nrel, f"{len(nregions)} noise-inconsistent region(s).",
                       [f["id"]], label="Noise residual")
        else:
            ctx.signal("noise_residual", modality, eid, 0.15, nrel, "Noise residual is consistent.",
                       label="Noise residual")

        # ---------------- JPEG 8x8 grid (DCT block) analysis --------------------
        grid = fx.jpeg_grid(gray)
        summary["jpeg_grid"] = grid
        if is_jpeg and grid["present"] and (grid["phase_x"] != 7 or grid["phase_y"] != 7):
            f = ctx.finding(modality, eid, "editing", "JPEG block grid misaligned",
                            f"The 8×8 DCT blocking pattern peaks at phase ({grid['phase_x']},{grid['phase_y']}) "
                            "instead of (7,7). The image was likely cropped or shifted after an earlier JPEG compression "
                            "(double compression).", {"type": "global"}, 0.45, 0.4, "jpeg_grid",
                            limitations="Platforms that crop/resize images produce the same pattern.",
                            alternatives=["Cropped for sharing", "Screenshot of a JPEG"])
            ctx.signal("jpeg_grid", modality, eid, 0.45, 0.4, "Misaligned JPEG grid (re-compression after crop).",
                       [f["id"]], label="JPEG/DCT grid")
        elif not is_jpeg and grid["present"]:
            f = ctx.finding(modality, eid, "editing", f"Hidden JPEG history in {fmt} file",
                            "A periodic 8×8 DCT block pattern is present although the file is not a JPEG: it was "
                            "previously JPEG-compressed and re-saved in a lossless format, which hides its compression history.",
                            {"type": "global"}, 0.4, 0.35, "jpeg_grid",
                            alternatives=["Screenshot or format conversion by a sharing app"])
            ctx.signal("jpeg_grid", modality, eid, 0.4, 0.35, "Lossless file with prior JPEG compression.",
                       [f["id"]], label="JPEG/DCT grid")
        else:
            ctx.signal("jpeg_grid", modality, eid, 0.2, 0.3, "No double-compression grid anomaly.",
                       label="JPEG/DCT grid")

        # ---------------- copy-move ---------------------------------------------
        cm = fx.copy_move(gray)
        if cm:
            vis = bgr.copy()
            for x1, y1, x2, y2 in cm["pairs"]:
                cv2.line(vis, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 1)
            for bb, col in ((cm["source_bbox"], (0, 255, 0)), (cm["target_bbox"], (0, 0, 255))):
                x, y, bw, bh = bb
                cv2.rectangle(vis, (x, y), (x + bw, y + bh), col, 2)
            out_p, curl = ctx.artifact_path(eid, f"{source_label}_copymove.jpg")
            cv2.imwrite(str(out_p), vis, [cv2.IMWRITE_JPEG_QUALITY, 88])
            summary["artifacts"]["copy_move"] = curl
            s = clamp(0.35 + 0.015 * cm["matches"], 0.35, 0.85)
            f = ctx.finding(modality, eid, "compositing", "Duplicated region (copy-move)",
                            f"{cm['matches']} keypoints match another part of the image with the same displacement "
                            f"({cm['offset'][0]:.0f}, {cm['offset'][1]:.0f}) px, which is typical of cloning to hide or add content.",
                            {"type": "regions", "regions": [{"bbox": cm["source_bbox"], "label": "source"},
                                                            {"bbox": cm["target_bbox"], "label": "copy"}],
                             "width": w, "height": h}, s, 0.5, "copy_move", [curl],
                            limitations="Repetitive patterns (tiles, windows, fabric) create false matches.",
                            alternatives=["Naturally repeating structure"])
            ctx.signal("copy_move", modality, eid, s, 0.5, f"{cm['matches']} consistent clone matches.", [f["id"]],
                       label="Copy-move detection")
        else:
            ctx.signal("copy_move", modality, eid, 0.15, 0.4, "No cloned regions found.", label="Copy-move detection")

    # ---------------- pretrained models ----------------------------------------
    faces = fx.detect_faces(gray)
    summary["faces"] = [list(f) for f in faces]
    if not lightweight and ctx.models_on("AI-image ensemble"):
        _ai_ensemble_and_tiles(ctx, ev, rgb, bgr, summary, modality, source_label)
        if faces:
            crops = []
            for box in faces:
                x0, y0, x1, y1 = fx.expand_box(box, w, h)
                crops.append(rgb.crop((x0, y0, x1, y1)))
            probs = models.face_deepfake_probs(crops) if ctx.models_on("face deepfake classifier") else False
            if probs is False:
                pass
            elif probs is None:
                ctx.limit(f"Face deepfake model unavailable ({models.model_error('face_deepfake')}).")
            else:
                summary["face_probs"] = [round(p, 4) for p in probs]
                pmax = max(probs)
                i = int(np.argmax(probs))
                rel = 0.45
                if pmax >= 0.6:
                    f = ctx.finding(modality, eid, "face-manipulation", "Face classified as manipulated",
                                    f"The ViT deepfake classifier gives {pmax:.0%} for face #{i + 1}.",
                                    {"type": "regions", "regions": [{"bbox": list(faces[i]), "label": f"face {pmax:.0%}"}],
                                     "width": w, "height": h}, pmax, rel, "face_deepfake_model",
                                    limitations="Face classifiers degrade on low resolution, unusual lighting and "
                                                "demographics under-represented in training data.",
                                    alternatives=["Beauty filter / portrait mode", "Low-light noise reduction"])
                    ctx.signal("face_deepfake_model", modality, eid, pmax, rel, f"max P(deepfake) over {len(faces)} face(s) = {pmax:.2f}",
                               [f["id"]], label="Face deepfake classifier")
                else:
                    ctx.signal("face_deepfake_model", modality, eid, pmax, rel,
                               f"max P(deepfake) over {len(faces)} face(s) = {pmax:.2f}", label="Face deepfake classifier")
    summary["dhash"] = fx.dhash(gray).astype(int).tolist()
    if not lightweight:
        _deep_metadata(ctx, ev, raw, pil, summary, modality)
        _manipulation(ctx, ev, rgb, bgr, summary, modality, source_label)
        summary["scores"] = _image_scores(ctx, eid, summary)
    return summary


# ------------------------------------------------------------------------------------------------------------
def _ai_ensemble_and_tiles(ctx, ev, rgb, bgr, summary, modality, label):
    from .. import detectors
    eid = ev["id"]
    res = detectors.AI_IMAGE.predict([rgb])
    if res["p"] is None:
        ctx.limit(f"AI-image detectors unavailable ({detectors.errors()}).")
        return
    p = float(res["p"][0])
    parts = {k: round(float(v[0]), 3) for k, v in res["parts"].items()}
    cal = detectors.AI_IMAGE.calib or {}
    acc = (cal.get("lodo") or {}).get("acc@0.5")
    summary["ai_ensemble"] = {"p": round(p, 4), "parts": parts, "calibrated": res["calibrated"]}
    summary["ai_image_prob"] = round(p, 4)
    rel = 0.85 if res["calibrated"] else 0.5
    desc = (f"A calibrated ensemble of {len(parts)} detectors ({', '.join(parts)}) estimates a {p:.0%} probability that "
            f"this picture was produced by an AI image generator."
            + (f" On held-out public benchmarks this ensemble is {acc:.0%} accurate." if acc else ""))
    if p >= 0.5:
        f = ctx.finding(modality, eid, "synthetic-generation", "AI-generated image", desc, {"type": "global"}, p, rel,
                        "ai_ensemble", limitations="Weakest on paintings/illustrations and heavily filtered photos; brand-new "
                                                   "generators can evade it.",
                        alternatives=["Digital artwork or heavy stylistic filter", "Very aggressive phone 'AI enhance' processing"])
        ctx.signal("ai_ensemble", modality, eid, p, rel, f"Calibrated P(AI-generated) = {p:.2f}", [f["id"]], label="AI-image ensemble",
                   extra={"parts": parts})
    else:
        ctx.signal("ai_ensemble", modality, eid, p, rel, f"Calibrated P(AI-generated) = {p:.2f}", label="AI-image ensemble",
                   extra={"parts": parts})

    # ---- tile heatmap: AI used on part of a real photo (inpainting / generative fill) ----
    cf = detectors.get("CommunityForensics ViT")
    if cf is None:
        return
    im = rgb
    if max(im.size) > 1536:
        s = 1536 / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.BICUBIC)
    W, H = im.size
    T, S = 384, 288
    if W < T or H < T:
        return
    xs = list(range(0, W - T + 1, S)) or [0]
    ys = list(range(0, H - T + 1, S)) or [0]
    if xs[-1] != W - T:
        xs.append(W - T)
    if ys[-1] != H - T:
        ys.append(H - T)
    boxes = [(x, y) for y in ys for x in xs]
    tiles = [im.crop((x, y, x + T, y + T)) for x, y in boxes]
    tp = cf.predict(tiles, crop=False)
    heat = np.zeros((H, W), np.float32)
    cnt = np.zeros((H, W), np.float32)
    for (x, y), v in zip(boxes, tp):
        heat[y:y + T, x:x + T] += v
        cnt[y:y + T, x:x + T] += 1
    heat /= np.maximum(cnt, 1)
    top = float(tp.max())
    frac = float((tp >= 0.8).mean())
    hidden = top * (1 - p) if (top >= 0.8 and frac < 0.6) else top * (1 - p) * 0.5
    summary["ai_tiles"] = {"n": len(tp), "top": round(top, 3), "flagged_frac": round(frac, 3), "p": round(hidden, 3)}
    sc = (H and rgb.height / H) or 1
    out = fx.heat_overlay(cv2.resize(bgr, (W, H)) if (W, H) != (bgr.shape[1], bgr.shape[0]) else bgr, heat, alpha=0.5)
    path, url = ctx.artifact_path(eid, f"{label}_aitiles.jpg")
    cv2.imwrite(str(path), out, [cv2.IMWRITE_JPEG_QUALITY, 86])
    summary.setdefault("artifacts", {})["ai_tiles"] = url
    if hidden >= 0.5:
        hot = [(x, y, v) for (x, y), v in zip(boxes, tp) if v >= 0.8]
        regs = [{"bbox": [int(x * sc), int(y * sc), int(T * sc), int(T * sc)], "label": f"AI {v:.0%}"} for x, y, v in hot[:4]]
        f = ctx.finding(modality, eid, "synthetic-generation", "AI-generated patch inside a real-looking photo",
                        f"Scanning the picture in {len(tp)} overlapping tiles, {len(hot)} tile(s) score up to {top:.0%} AI-generated "
                        f"while the picture as a whole scores {p:.0%}. This pattern fits generative fill or AI inpainting used "
                        "to add, remove or change part of a real photo.",
                        {"type": "regions", "regions": regs, "width": rgb.width, "height": rgb.height}, hidden, 0.6, "ai_tiles", [url],
                        limitations="Smooth skies, bokeh and heavily processed areas can raise individual tiles.",
                        alternatives=["Phone portrait-mode blur", "Strong local denoising"])
        ctx.signal("ai_tiles", modality, eid, hidden, 0.6, f"Top tile {top:.2f} vs global {p:.2f}", [f["id"]], label="AI tile scan")
    else:
        ctx.signal("ai_tiles", modality, eid, hidden, 0.5, f"No localised AI patch (top tile {top:.2f}).", label="AI tile scan")


def _deep_metadata(ctx, ev, raw, pil, summary, modality):
    from .metadata import analyze_metadata
    eid = ev["id"]
    md = analyze_metadata(raw, pil, summary.get("exif") or {})
    summary["metadata_deep"] = {k: v for k, v in md.items() if k != "observations"}
    best = 0.0
    for o in md["observations"]:
        best = max(best, o["strength"])
        if o["strength"] < 0.4:
            continue
        arts = []
        if o["kind"] == "thumb_mismatch" and o.get("diff") is not None:
            d = o["diff"]
            vis = cv2.applyColorMap(np.clip(d / (np.percentile(d, 99) + 1e-6) * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
            path, url = ctx.artifact_path(eid, "thumbnail_diff.png")
            cv2.imwrite(str(path), cv2.resize(vis, (vis.shape[1] * 3, vis.shape[0] * 3), interpolation=cv2.INTER_NEAREST))
            arts.append(url)
        cat = "synthetic-generation" if o["kind"] in ("c2pa_ai", "iptc_ai", "xmp_ai_tool", "exif_ai_software") else "metadata"
        f = ctx.finding(modality, eid, cat, {"thumb_mismatch": "EXIF preview doesn't match the picture",
                                             "xmp_history": "Edit history recorded in the file",
                                             "exif_injected": "Camera data looks added by software",
                                             "c2pa_ai": "Content Credentials name an AI tool",
                                             "iptc_ai": "File declares itself AI-generated",
                                             "xmp_ai_tool": "AI tool recorded in the file",
                                             "exif_ai_software": "AI tool recorded in EXIF"}.get(o["kind"], "Metadata observation"),
                        o["text"], {"type": "metadata", "fields": [o["kind"]]}, o["strength"], 0.8, "metadata_deep", arts,
                        limitations="Metadata can be edited by anyone; it supports but never replaces pixel analysis.")
        ctx.signal("metadata_deep", modality, eid, o["strength"], 0.8, o["text"][:140], [f["id"]], label="Deep metadata")
        if cat == "synthetic-generation":
            summary["generator_evidence"] = max(summary.get("generator_evidence", 0), o["strength"])
    summary["metadata_strength"] = best


def _manipulation(ctx, ev, rgb, bgr, summary, modality, label):
    """Learned forgery detection (TruFor) when installed; otherwise the calibrated classical model (weak, AUC≈0.67)."""
    from . import trufor
    eid = ev["id"]
    out = None
    if ctx.opts.get("models", True) and trufor.available():
        try:
            out = trufor.analyze(rgb)
        except Exception as e:  # pragma: no cover
            ctx.limit(f"TruFor forgery detector failed ({e}).")
    if out is not None:
        p = out["score"]
        hm = out["map"]
        summary["trufor"] = {"score": round(p, 4), "area": round(float((hm > 0.5).mean()), 4)}
        vis = fx.heat_overlay(cv2.resize(bgr, (hm.shape[1], hm.shape[0])), hm, alpha=0.55)
        path, url = ctx.artifact_path(eid, f"{label}_trufor.jpg")
        cv2.imwrite(str(path), vis, [cv2.IMWRITE_JPEG_QUALITY, 86])
        summary.setdefault("artifacts", {})["trufor"] = url
        sc = rgb.width / hm.shape[1]
        mask = (hm > 0.5).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
        regs = sorted([stats[i] for i in range(1, n) if stats[i][4] > 0.002 * mask.size], key=lambda s: -s[4])[:4]
        regions = [{"bbox": [int(s[0] * sc), int(s[1] * sc), int(s[2] * sc), int(s[3] * sc)], "label": "edited"} for s in regs]
        if p >= 0.5:
            f = ctx.finding(modality, eid, "compositing", "Manipulated region detected (TruFor)",
                            f"TruFor, a forgery detector trained on spliced, copy-moved and AI-inpainted photos (CVPR 2023), gives "
                            f"{p:.0%} that this picture was manipulated and marks {summary['trufor']['area']:.0%} of it as altered.",
                            {"type": "regions", "regions": regions, "width": rgb.width, "height": rgb.height}, p, 0.75, "trufor", [url],
                            limitations="Very strong compression or resizing after the edit weakens localisation.",
                            alternatives=["Heavy local retouching for aesthetics"])
            ctx.signal("trufor", modality, eid, p, 0.75, f"TruFor integrity score {p:.2f}", [f["id"]], label="TruFor forgery detector")
        else:
            ctx.signal("trufor", modality, eid, p, 0.75, f"TruFor integrity score {p:.2f} (no manipulation)", label="TruFor forgery detector")
        return
    calib = __import__("app.detectors", fromlist=["load_calib"]).load_calib("manipulation")
    if calib:
        feats = fx.classical_features(rgb)
        x = (np.array([feats[k] for k in calib["features"]]) - np.array(calib["mean"])) / np.array(calib["scale"])
        p = float(1 / (1 + np.exp(-(x @ np.array(calib["coef"]) + calib["intercept"]))))
        summary["manip_classical"] = {"p": round(p, 4), "cv_auc": calib["cv"]["auc"]}
        ctx.signal("manip_model", modality, eid, p, 0.3,
                   f"Classical forensic model P(manipulated) = {p:.2f} (benchmark AUC {calib['cv']['auc']:.2f}: weak evidence)",
                   label="Classical manipulation model")


def _image_scores(ctx, eid, s) -> dict:
    sig = {x["detector"]: x for x in ctx.signals if x["evidence_id"] == eid}

    def sc(d, default=None):
        return sig[d]["score"] if d in sig else default
    gen = s.get("generator_evidence", 0)
    ai = max(sc("ai_ensemble", 0) or 0, gen, sc("generator_metadata", 0) if (sc("generator_metadata", 0) or 0) >= 0.85 else 0)
    if "ai_ensemble" not in sig and not gen:
        ai = None
    cm = sc("copy_move", 0) or 0
    tru = sc("trufor")
    md = s.get("metadata_strength", 0)
    edit_md = max(md if md >= 0.45 else 0, sc("exif_software", 0) if (sc("exif_software", 0) or 0) >= 0.55 else 0)
    classical = sc("manip_model")
    cmv = min(cm, 0.65) if cm >= 0.6 else 0  # copy-move is not benchmarked: it can suggest ('likely'), never decide alone
    # classical model excluded: end-to-end benchmark showed it fires on 15% of real AND 17% of fake images
    manipulation = max(tru or 0, edit_md, cmv)
    if tru is None and classical is None and not edit_md and cm < 0.6:
        manipulation = min(0.35, (classical or 0.3))
    compositing = max(tru or 0, cmv) if (tru is not None or cm >= 0.6) else min(0.35, cm)
    face = sc("face_ensemble", sc("face_deepfake_model"))
    return {"ai_generated": ai, "face_swap": face, "manipulation": round(manipulation, 3), "compositing": round(compositing, 3),
            "hidden_ai": sc("ai_tiles"), "metadata": round(max(md, 0.3 if not s.get("exif") else 0.1), 3)}
