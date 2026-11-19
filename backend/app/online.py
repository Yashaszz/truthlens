"""'Seen online': find EXACT copies of an uploaded image / video keyframes on the public web.

Providers (whichever key is set in backend/.env):
  A) SerpAPI Google Lens 'exact matches' (needs a public image URL → keyframe uploaded to imgbb, auto-deleted in 10 min)
  B) Google Cloud Vision Web Detection (image sent directly; returns pages containing full matching images)
Every candidate is then verified locally (perceptual hash + feature matching) so only true duplicates are reported:
cropped / resized / recompressed reposts pass, merely similar-looking content does not."""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import logging
import os
import socket
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .analyzers import forensics as fx

log = logging.getLogger("truthlens.online")
UA = "Mozilla/5.0 (TruthLens forensic tool)"
FACT_CHECKERS = ["altnews.in", "boomlive.in", "factly.in", "pib.gov.in", "newschecker.in", "vishvasnews.com", "factcrescendo",
                 "thequint.com/news/webqoof", "indiatoday.in/fact-check", "aajtak.in/fact-check", "newsmeter.in", "fact-check",
                 "factcheck", "afp.com", "reuters.com/fact-check", "snopes.com", "politifact.com", "fullfact.org", "leadstories.com",
                 "apnews.com/hub/ap-fact-check", "logicallyfacts.com", "dfrac.org"]
SOCIAL = {"x.com": "X", "twitter.com": "X", "facebook.com": "Facebook", "fb.watch": "Facebook", "instagram.com": "Instagram",
          "youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok", "reddit.com": "Reddit", "threads.net": "Threads",
          "linkedin.com": "LinkedIn", "sharechat.com": "ShareChat", "telegram": "Telegram", "t.me": "Telegram"}


def provider() -> str | None:
    if os.getenv("GOOGLE_VISION_KEY"):
        return "vision"
    if os.getenv("SERPAPI_KEY") and os.getenv("IMGBB_KEY"):
        return "serpapi"
    return None


def missing_keys() -> list[str]:
    if provider():
        return []
    return [k for k in ("SERPAPI_KEY", "IMGBB_KEY") if not os.getenv(k)]


# ------------------------------------------------------------------ http helpers
def _public_url(url: str) -> bool:
    try:
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(u.hostname))
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except Exception:
        return False


def _get_json(url: str, data: bytes | None = None, timeout: int = 40) -> dict:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json" if data and data[:1] == b"{" else
                                                         "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _download_image(url: str, limit: int = 6_000_000) -> Image.Image | None:
    if not _public_url(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            b = r.read(limit + 1)
        if len(b) > limit:
            return None
        return Image.open(io.BytesIO(b)).convert("RGB")
    except Exception:
        return None


def _jpeg_b64(im: Image.Image, max_side: int = 1280) -> str:
    im = im.convert("RGB")
    if max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------------ providers
def _serpapi(frame: Image.Image) -> list[dict]:
    up = _get_json(f"https://api.imgbb.com/1/upload?expiration=600&key={urllib.parse.quote(os.environ['IMGBB_KEY'])}",
                   urllib.parse.urlencode({"image": _jpeg_b64(frame)}).encode())
    url = up["data"]["url"]
    q = urllib.parse.urlencode({"engine": "google_lens", "type": "exact_matches", "url": url, "hl": "en",
                                "api_key": os.environ["SERPAPI_KEY"]})
    res = _get_json(f"https://serpapi.com/search.json?{q}", timeout=60)
    if res.get("error"):
        raise RuntimeError(res["error"])
    out = []
    for m in res.get("exact_matches", []) or []:
        out.append({"link": m.get("link"), "title": m.get("title"), "source": m.get("source"), "date": m.get("date"),
                    "thumb": m.get("thumbnail") or m.get("image")})
    return out


def _vision(frame: Image.Image) -> list[dict]:
    body = json.dumps({"requests": [{"image": {"content": _jpeg_b64(frame)},
                                     "features": [{"type": "WEB_DETECTION", "maxResults": 30}]}]}).encode()
    res = _get_json(f"https://vision.googleapis.com/v1/images:annotate?key={urllib.parse.quote(os.environ['GOOGLE_VISION_KEY'])}", body)
    if res.get("error"):
        raise RuntimeError(res["error"].get("message"))
    wd = (res.get("responses") or [{}])[0].get("webDetection", {}) or {}
    out = []
    for p in wd.get("pagesWithMatchingImages", []) or []:
        imgs = (p.get("fullMatchingImages") or []) + (p.get("partialMatchingImages") or [])
        out.append({"link": p.get("url"), "title": p.get("pageTitle", "").replace("<b>", "").replace("</b>", ""),
                    "source": urllib.parse.urlparse(p.get("url", "")).hostname, "date": None,
                    "thumb": imgs[0]["url"] if imgs else None, "full": bool(p.get("fullMatchingImages"))})
    return out


# ------------------------------------------------------------------ verification
def similarity(a: Image.Image, b: Image.Image) -> float:
    """1.0 = identical picture. Combines a 256-bit difference hash (robust to resize/recompression) with
    ORB feature matching + RANSAC (robust to crops and overlays)."""
    ga = cv2.cvtColor(np.asarray(a), cv2.COLOR_RGB2GRAY)
    gb = cv2.cvtColor(np.asarray(b), cv2.COLOR_RGB2GRAY)
    hd = float(np.mean(fx.dhash(ga) != fx.dhash(gb)))
    s_hash = 1 - hd
    try:
        orb = cv2.ORB_create(1500)
        ka, da = orb.detectAndCompute(cv2.resize(ga, (512, int(512 * ga.shape[0] / ga.shape[1]))), None)
        kb, db = orb.detectAndCompute(cv2.resize(gb, (512, int(512 * gb.shape[0] / gb.shape[1]))), None)
        inl = 0
        if da is not None and db is not None and len(ka) > 10 and len(kb) > 10:
            ms = [m for m, n in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2) if m.distance < 0.75 * n.distance] \
                if len(kb) > 1 else []
            if len(ms) >= 8:
                src = np.float32([ka[m.queryIdx].pt for m in ms]); dst = np.float32([kb[m.trainIdx].pt for m in ms])
                _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
                inl = int(mask.sum()) if mask is not None else 0
        s_orb = min(1.0, inl / 40)
    except Exception:
        s_orb = 0.0
    return max(s_hash if hd <= 0.2 else s_hash * 0.6, s_orb)


EXACT = 0.8


def _platform(link: str) -> tuple[str, bool]:
    host = (urllib.parse.urlparse(link or "").hostname or "").lower()
    plat = next((v for k, v in SOCIAL.items() if k in host or k in (link or "")), None)
    fc = any(f in (link or "").lower() for f in FACT_CHECKERS)
    return plat or host.replace("www.", ""), fc


def search_frames(frames: list[Image.Image]) -> dict:
    prov = provider()
    if prov is None:
        return {"status": "not_configured", "missing": missing_keys()}
    fn = _serpapi if prov == "serpapi" else _vision
    found: dict[str, dict] = {}
    errors, candidates = [], 0
    for frame in frames:
        try:
            cands = [c for c in fn(frame) if c.get("link")]
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
            continue
        candidates += len(cands)

        def check(c):
            th = _download_image(c["thumb"]) if c.get("thumb") else None
            return c, (similarity(frame, th) if th is not None else None)
        with ThreadPoolExecutor(8) as ex:
            for c, sim in ex.map(check, cands[:30]):
                if sim is None and not c.get("full"):
                    continue  # couldn't verify and provider didn't claim a full match
                sim = sim if sim is not None else 0.85
                if sim < EXACT:
                    continue
                plat, fc = _platform(c["link"])
                prev = found.get(c["link"])
                if prev is None or sim > prev["similarity"]:
                    found[c["link"]] = {"link": c["link"], "title": (c.get("title") or "")[:160], "site": plat,
                                        "date": c.get("date"), "thumb": c.get("thumb"), "similarity": round(sim, 3),
                                        "fact_check": fc}
    matches = sorted(found.values(), key=lambda m: (not m["fact_check"], -m["similarity"]))
    status = "error" if errors and not matches and not candidates else ("found" if matches else "none")
    return {"status": status, "provider": prov, "frames_searched": len(frames), "candidates": candidates,
            "matches": matches, "fact_checks": sum(m["fact_check"] for m in matches), "errors": errors[:3]}


def frames_for(evidence_path: Path, modality: str, n: int = 3) -> list[Image.Image]:
    if modality == "image":
        return [Image.open(evidence_path).convert("RGB")]
    cap = cv2.VideoCapture(str(evidence_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out = []
    for pos in np.linspace(0.12, 0.88, n * 2):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * pos))
        ok, fr = cap.read()
        if not ok:
            continue
        has_face = bool(fx.detect_faces(fr))
        out.append((has_face, Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))))
    cap.release()
    out.sort(key=lambda t: not t[0])  # prefer frames with a visible face (most likely to be reposted thumbnails)
    return [im for _, im in out[:n]]
