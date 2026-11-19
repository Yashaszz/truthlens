"""Deep metadata forensics for images: EXIF thumbnail vs image, XMP edit history, C2PA claim generator,
camera-EXIF plausibility. Returns structured observations; image.py turns them into findings/signals."""
from __future__ import annotations

import io
import re

import cv2
import numpy as np
from PIL import Image

AI_TOOLS = ["openai", "dall-e", "dall·e", "chatgpt", "gpt-4o", "sora", "midjourney", "stable diffusion", "stability ai",
            "adobe firefly", "firefly", "imagen", "gemini", "google ai", "bing image creator", "microsoft designer",
            "leonardo", "ideogram", "flux", "runway", "canva ai", "meta ai", "grok", "krea", "playground ai",
            "nightcafe", "dreamstudio", "novelai", "comfyui", "automatic1111", "invokeai", "fooocus"]
EDITORS = ["photoshop", "lightroom", "gimp", "affinity", "pixelmator", "snapseed", "picsart", "facetune", "faceapp",
           "remini", "meitu", "canva", "photopea", "luminar", "capture one", "darktable", "paint.net", "airbrush", "lensa"]


def _exif_thumbnail(raw: bytes) -> Image.Image | None:
    """Extract the JPEG thumbnail embedded in the EXIF APP1 segment (if any)."""
    i = raw.find(b"\xff\xe1")
    while i != -1 and i < 65536 * 4:
        seg_len = int.from_bytes(raw[i + 2:i + 4], "big")
        seg = raw[i + 4:i + 2 + seg_len]
        if seg.startswith(b"Exif\x00\x00"):
            s = seg.find(b"\xff\xd8", 10)
            if s != -1:
                e = seg.find(b"\xff\xd9", s)
                if e != -1:
                    try:
                        return Image.open(io.BytesIO(seg[s:e + 2])).convert("RGB")
                    except Exception:
                        return None
            return None
        i = raw.find(b"\xff\xe1", i + 2)
    return None


def _thumb_match(thumb: Image.Image, img: Image.Image) -> dict:
    tw, th = thumb.size
    iw, ih = img.size
    ar_t, ar_i = tw / th, iw / ih
    # thumbnails may be letterboxed; compare on the central region matching the image aspect ratio
    small = np.asarray(img.resize((tw, th), Image.BILINEAR).convert("L"), np.float32)
    t = np.asarray(thumb.convert("L"), np.float32)
    rot = None
    best = -1.0
    for k in range(4):
        cand = np.rot90(np.asarray(img.convert("L").resize((tw, th) if k % 2 == 0 else (th, tw)), np.float32), k)
        if cand.shape != t.shape:
            continue
        a, b = cand - cand.mean(), t - t.mean()
        c = float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))
        if c > best:
            best, rot = c, k
    diff = np.abs(cv2.GaussianBlur(small, (3, 3), 0) - cv2.GaussianBlur(t, (3, 3), 0))
    return {"corr": round(best, 3), "aspect_thumb": round(ar_t, 3), "aspect_image": round(ar_i, 3),
            "aspect_mismatch": abs(ar_t - ar_i) > 0.06 and abs(1 / ar_t - ar_i) > 0.06, "rotation": rot,
            "_diff": diff}


def _xmp(raw: bytes) -> str:
    s = raw.find(b"<x:xmpmeta")
    if s == -1:
        s = raw.find(b"<?xpacket begin")
    if s == -1:
        return ""
    e = raw.find(b"</x:xmpmeta>", s)
    return raw[s:e + 12 if e != -1 else s + 200_000].decode("utf-8", "ignore")


def analyze_metadata(raw: bytes, pil: Image.Image, exif: dict) -> dict:
    out: dict = {"observations": []}
    head = raw[:6_000_000]
    low = head.lower()

    # --- C2PA / content credentials ---------------------------------------------------------
    if b"c2pa" in low or b"jumb" in low[:400_000]:
        gens = sorted({t for t in AI_TOOLS if t.encode() in low})
        cg = re.findall(rb"claim_generator[^\x00]{0,4}([\x20-\x7e]{3,80})", head)
        out["c2pa"] = {"present": True, "claim_generator": [c.decode("ascii", "ignore") for c in cg[:3]], "ai_tools": gens}
        if gens or any(re.search(r"(openai|firefly|dall|imagen|gemini|bing|designer)", c.decode("ascii", "ignore"), re.I) for c in cg):
            out["observations"].append({"kind": "c2pa_ai", "strength": 0.95,
                                        "text": "Content Credentials (C2PA) in the file name a generative-AI tool: "
                                                + ", ".join(gens or [c.decode('ascii', 'ignore') for c in cg[:2]])})
        else:
            out["observations"].append({"kind": "c2pa_present", "strength": 0.2,
                                        "text": "Content Credentials (C2PA) present; provenance chain can be verified with a C2PA viewer."})

    # --- XMP edit history -----------------------------------------------------------------------
    xmp = _xmp(head)
    if xmp:
        agents = sorted(set(re.findall(r'(?:softwareAgent|CreatorTool)\s*=\s*"([^"]{2,80})"', xmp) +
                            re.findall(r"<(?:stEvt:softwareAgent|xmp:CreatorTool)>([^<]{2,80})<", xmp)))
        actions = re.findall(r'stEvt:action\s*=\s*"([^"]+)"', xmp) + re.findall(r"<stEvt:action>([^<]+)<", xmp)
        dst = re.findall(r"DigitalSourceType[^>]*?(?:>|=\")([^<\"]{5,120})", xmp)
        out["xmp"] = {"agents": agents[:8], "actions": len(actions), "digital_source_type": dst[:2]}
        ai_agents = [a for a in agents if any(t in a.lower() for t in AI_TOOLS)]
        ed_agents = [a for a in agents if any(t in a.lower() for t in EDITORS)]
        if any("trainedalgorithmicmedia" in d.lower() for d in dst):
            out["observations"].append({"kind": "iptc_ai", "strength": 0.95,
                                        "text": "XMP declares the image as 'trained algorithmic media' (AI-generated) under the IPTC standard."})
        if ai_agents:
            out["observations"].append({"kind": "xmp_ai_tool", "strength": 0.9, "text": "XMP records a generative-AI tool: " + ", ".join(ai_agents[:3])})
        if ed_agents or len(actions) >= 2:
            out["observations"].append({"kind": "xmp_history", "strength": 0.6 if ed_agents else 0.45,
                                        "text": f"XMP edit history records {len(actions)} save/edit action(s)"
                                                + (f" in {', '.join(ed_agents[:3])}" if ed_agents else "") + "."})

    # --- EXIF thumbnail vs main image -----------------------------------------------------------
    thumb = _exif_thumbnail(head) if raw[:2] == b"\xff\xd8" else None
    if thumb is not None and min(thumb.size) >= 32:
        m = _thumb_match(thumb, pil.convert("RGB"))
        out["thumbnail"] = {k: v for k, v in m.items() if not k.startswith("_")}
        if m["corr"] < 0.6 or m["aspect_mismatch"]:
            out["observations"].append({"kind": "thumb_mismatch", "strength": 0.85 if m["corr"] < 0.4 else 0.7,
                                        "text": "The preview thumbnail stored in the EXIF data does not match the picture "
                                                f"(similarity {max(0, m['corr']):.0%}{', different shape' if m['aspect_mismatch'] else ''}). "
                                                "The image was changed after the camera wrote it, but the preview was not updated.",
                                        "diff": m["_diff"]})
        else:
            out["observations"].append({"kind": "thumb_match", "strength": 0.15,
                                        "text": f"EXIF preview thumbnail matches the picture ({m['corr']:.0%})."})

    # --- camera EXIF plausibility ------------------------------------------------------------------
    make, model = exif.get("Make"), exif.get("Model")
    if make or model:
        core = ["DateTimeOriginal", "ExposureTime", "FNumber", "ISOSpeedRatings", "FocalLength"]
        alt = {"ISOSpeedRatings": "PhotographicSensitivity"}
        missing = [k for k in core if k not in exif and alt.get(k, "") not in exif]
        has_maker = any(k in exif for k in ("MakerNote", "37500"))
        out["camera"] = {"make": make, "model": model, "missing_core": missing, "maker_note": has_maker}
        if len(missing) >= 3:
            out["observations"].append({"kind": "exif_injected", "strength": 0.6,
                                        "text": f"Camera '{make or ''} {model or ''}' is named but {len(missing)} fields every camera writes are "
                                                f"missing ({', '.join(missing[:4])}), which suggests the camera data was added or edited by software."})
    sw = f"{exif.get('Software', '')} {exif.get('ProcessingSoftware', '')}".lower()
    ai_sw = [t for t in AI_TOOLS if t in sw]
    if ai_sw:
        out["observations"].append({"kind": "exif_ai_software", "strength": 0.9, "text": f"EXIF 'Software' names an AI tool: {exif.get('Software')}"})
    return out
