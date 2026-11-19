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
    ela_rel = (0.55 if is_jpeg else 0.3) * (0.6 if lightweight else 1.0) * (0.7 if max(h, w) < 400 else 1.0)
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
        nrel = 0.4 if max(h, w) >= 400 else 0.25
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
    if not lightweight:
        p_ai = models.ai_image_prob(rgb) if ctx.models_on("AI-image classifier") else False
        if p_ai is False:
            pass
        elif p_ai is None:
            ctx.limit(f"AI-image classifier unavailable ({models.model_error('ai_image')}); relying on classical detectors.")
        else:
            summary["ai_image_prob"] = round(p_ai, 4)
            rel = 0.45
            if p_ai >= 0.6:
                f = ctx.finding(modality, eid, "synthetic-generation", "Classifier: likely AI-generated imagery",
                                f"A pretrained Swin classifier ({models.MODELS['ai_image']}) assigns {p_ai:.0%} probability "
                                "that the image is synthetic.", {"type": "global"}, p_ai, rel, "ai_image_model",
                                limitations="Trained on older generators; heavy compression, filters and art styles cause "
                                            "false positives; newer generators may evade it.",
                                alternatives=["Stylised photo / heavy filter", "Digital artwork"])
                ctx.signal("ai_image_model", modality, eid, p_ai, rel, f"P(synthetic) = {p_ai:.2f}", [f["id"]],
                           label="AI-image classifier")
            else:
                ctx.signal("ai_image_model", modality, eid, p_ai, rel, f"P(synthetic) = {p_ai:.2f}",
                           label="AI-image classifier")
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
    return summary
