"""Classical image-forensics primitives shared by the image and video analyzers."""
from __future__ import annotations

import io
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

_FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def to_bgr(pil: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)


_YUNET_PATH = Path(__file__).resolve().parents[1] / "assets" / "face_detection_yunet_2023mar.onnx"
_yunet = None
_yunet_lock = threading.Lock()


def detect_faces(img: np.ndarray, min_frac: float = 0.06, min_conf: float = 0.8) -> list[tuple[int, int, int, int]]:
    """Faces as (x, y, w, h). Uses OpenCV YuNet (neural, few false positives); falls back to Haar if unavailable.
    The old Haar-only detector boxed textures (lapels, grilles) as faces, and those crops were then scored as faces."""
    global _yunet
    h, w = img.shape[:2]
    m = max(24, int(min(h, w) * min_frac))
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
    if _YUNET_PATH.exists() and hasattr(cv2, "FaceDetectorYN"):
        with _yunet_lock:
            if _yunet is None:
                _yunet = cv2.FaceDetectorYN.create(str(_YUNET_PATH), "", (320, 320), min_conf, 0.3, 50)
            s = 1024 / max(h, w) if max(h, w) > 1024 else 1.0
            sm = cv2.resize(bgr, None, fx=s, fy=s) if s < 1 else bgr
            _yunet.setInputSize((sm.shape[1], sm.shape[0]))
            _, found = _yunet.detect(sm)
        faces = []
        for r in (found if found is not None else []):
            x, y, fw, fh = (int(v / s) for v in r[:4])
            if r[-1] >= min_conf and min(fw, fh) >= m:
                faces.append((max(0, x), max(0, y), fw, fh))
        return sorted(faces, key=lambda f: -f[2] * f[3])[:5]
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = _FACE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=8, minSize=(m, m))
    return sorted([tuple(int(v) for v in f) for f in faces], key=lambda f: -f[2] * f[3])[:5]


def expand_box(box, w, h, margin=0.25):
    x, y, bw, bh = box
    dx, dy = int(bw * margin), int(bh * margin)
    x0, y0 = max(0, x - dx), max(0, y - dy)
    x1, y1 = min(w, x + bw + dx), min(h, y + bh + dy)
    return x0, y0, x1, y1


def ela_map(pil: Image.Image, quality: int = 90) -> np.ndarray:
    """Error Level Analysis: per-pixel max abs difference after one JPEG re-save."""
    rgb = pil.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    re = np.asarray(Image.open(buf).convert("RGB"), np.int16)
    return np.abs(np.asarray(rgb, np.int16) - re).max(axis=2).astype(np.float32)


def _blocks(a: np.ndarray, b: int) -> np.ndarray:
    h, w = (a.shape[0] // b) * b, (a.shape[1] // b) * b
    return a[:h, :w].reshape(h // b, b, w // b, b)


def block_mean(a: np.ndarray, b: int) -> np.ndarray:
    return _blocks(a, b).mean(axis=(1, 3))


def block_std(a: np.ndarray, b: int) -> np.ndarray:
    return _blocks(a, b).std(axis=(1, 3))


def texture_map(gray: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


def robust_z(v: np.ndarray) -> np.ndarray:
    med = np.median(v)
    mad = np.median(np.abs(v - med)) * 1.4826 + 1e-6
    return (v - med) / mad


def texture_normalised_z(values: np.ndarray, texture: np.ndarray) -> np.ndarray:
    """Regress block values on block texture and return robust z-scores of the residuals.
    This stops ordinary high-detail areas (edges, foliage) from being flagged just for being detailed."""
    x, y = texture.ravel(), values.ravel()
    if x.std() > 1e-6:
        A = np.vstack([x, np.ones_like(x)]).T
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
    else:
        resid = y - y.mean()
    return robust_z(resid).reshape(values.shape)


def outlier_regions(z: np.ndarray, block: int, thresh: float, min_blocks: int = 3,
                    two_sided: bool = False, max_regions: int = 5) -> list[dict]:
    mask = (np.abs(z) > thresh) if two_sided else (z > thresh)
    mask = mask.astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    regions = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_blocks:
            continue
        zz = z[labels == i]
        regions.append({"bbox": [int(x * block), int(y * block), int(w * block), int(h * block)],
                        "blocks": int(area), "mean_z": float(np.mean(np.abs(zz))),
                        "max_z": float(np.max(np.abs(zz)))})
    total = z.size
    for r in regions:
        r["area_frac"] = r["blocks"] / total
    regions.sort(key=lambda r: -r["mean_z"] * np.sqrt(r["blocks"]))
    return regions[:max_regions]


def heat_overlay(bgr: np.ndarray, heat: np.ndarray, regions: list[dict] | None = None,
                 alpha: float = 0.55, color=(0, 0, 255)) -> np.ndarray:
    h, w = bgr.shape[:2]
    hm = heat.astype(np.float32)
    hi = np.percentile(hm, 99.5) or 1.0
    hm = np.clip(hm / hi, 0, 1)
    hm = cv2.resize((hm * 255).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
    colored = cv2.applyColorMap(hm, cv2.COLORMAP_INFERNO)
    out = cv2.addWeighted(bgr, 1 - alpha, colored, alpha, 0)
    for i, r in enumerate(regions or []):
        x, y, bw, bh = r["bbox"]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), color, max(2, w // 400))
        cv2.putText(out, f"R{i + 1}", (x + 3, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return out


def jpeg_grid(gray: np.ndarray) -> dict:
    """8x8 blocking-artifact phase. A JPEG saved once and untouched has its block boundaries at
    phase 7 (between pixel 7 and 8). Peaks at another phase suggest cropping/shift after compression;
    a strong grid in a PNG suggests it was previously a JPEG."""
    g = gray.astype(np.float32)
    dx = np.abs(np.diff(g, axis=1)).mean(axis=0)
    dy = np.abs(np.diff(g, axis=0)).mean(axis=1)
    px = np.array([dx[i::8].mean() for i in range(8)])
    py = np.array([dy[i::8].mean() for i in range(8)])
    sx = float(px.max() / (np.median(px) + 1e-6))
    sy = float(py.max() / (np.median(py) + 1e-6))
    return {"phase_x": int(px.argmax()), "phase_y": int(py.argmax()), "strength_x": round(sx, 3),
            "strength_y": round(sy, 3), "present": bool(sx > 1.08 and sy > 1.08)}


def copy_move(gray: np.ndarray, max_side: int = 1200) -> dict | None:
    """ORB self-matching: groups of keypoints that match elsewhere in the image with a consistent
    displacement vector indicate a duplicated (cloned) region."""
    scale = min(1.0, max_side / max(gray.shape))
    g = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    orb = cv2.ORB_create(nfeatures=4000)
    kps, des = orb.detectAndCompute(g, None)
    if des is None or len(kps) < 30:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = bf.knnMatch(des, des, k=3)
    min_dist = max(30, int(0.04 * max(g.shape)))
    pairs = []
    for ms in matches:
        for m in ms[1:]:
            if m.distance > 40:
                continue
            p1, p2 = np.array(kps[m.queryIdx].pt), np.array(kps[m.trainIdx].pt)
            if np.linalg.norm(p1 - p2) < min_dist:
                continue
            if p1[0] > p2[0] or (p1[0] == p2[0] and p1[1] > p2[1]):
                p1, p2 = p2, p1
            pairs.append((p1, p2))
            break
    if len(pairs) < 8:
        return None
    off = np.array([p2 - p1 for p1, p2 in pairs])
    binsz = max(8, int(0.015 * max(g.shape)))
    keys = [tuple(k) for k in np.round(off / binsz).astype(int)]
    from collections import Counter
    ranked = Counter(keys).most_common()
    key, count = ranked[0]
    if count < 16:  # fewer matches are routinely produced by repeated structure (tiles, flat shapes, text)
        return None
    # Periodic structure (window grilles, blinds, tiles, brickwork, fabric) matches itself at several offsets
    # that are multiples of the pattern period. Genuine cloning produces one dominant offset.
    ko = np.array(key, dtype=float)
    for k2, c2 in ranked[1:6]:
        k2 = np.array(k2, dtype=float)
        if c2 >= 0.35 * count:
            return None  # a second strong offset → lattice / repetition, not a clone
        for mult in (2.0, 0.5, 3.0):
            if np.linalg.norm(k2 - ko * mult) <= 1.5 and c2 >= 0.15 * count:
                return None  # harmonics of the same period
    sel = [pairs[i] for i, k in enumerate(keys) if k == key]
    src = np.array([p for p, _ in sel]) / scale
    dst = np.array([q for _, q in sel]) / scale

    def bbox(pts):
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        return [int(x0), int(y0), int(max(8, x1 - x0)), int(max(8, y1 - y0))]

    sb, db = bbox(src), bbox(dst)
    shift = float(np.linalg.norm(ko * binsz / scale))
    region = max(sb[2], sb[3], db[2], db[3])
    overlap_x = min(sb[0] + sb[2], db[0] + db[2]) - max(sb[0], db[0])
    overlap_y = min(sb[1] + sb[3], db[1] + db[3]) - max(sb[1], db[1])
    if (overlap_x > 0 and overlap_y > 0) or shift < 1.2 * region:
        return None  # source and copy touch/overlap: self-similar texture next to itself, not a moved clone

    return {"matches": int(count), "offset": [float(v) for v in (off[[i for i, k in enumerate(keys) if k == key]].mean(axis=0) / scale)],
            "source_bbox": bbox(src), "target_bbox": bbox(dst),
            "pairs": [[*map(float, p), *map(float, q)] for p, q in zip(src[:60], dst[:60])]}


MANIP_FEATURES = ["ela_top", "ela_area", "ela_p99", "ela_spread", "noise_top", "noise_area", "noise_p99",
                  "cm_matches", "grid_max", "grid_misaligned", "blockiness_var"]


def classical_features(pil: Image.Image, max_side: int = 1024) -> dict:
    """Compact numeric description of local inconsistencies, used by the calibrated manipulation model."""
    rgb = pil.convert("RGB")
    if max(rgb.size) > max_side:
        s = max_side / max(rgb.size)
        rgb = rgb.resize((max(16, int(rgb.width * s)), max(16, int(rgb.height * s))), Image.BILINEAR)
    bgr = to_bgr(rgb)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    B = 16
    tex = texture_map(gray)
    ela = ela_map(rgb)
    z = texture_normalised_z(block_mean(ela, B), block_mean(tex, B))
    er = outlier_regions(z, B, thresh=4.0, min_blocks=3)
    resid = gray.astype(np.float32) - cv2.medianBlur(gray, 3).astype(np.float32)
    nz = texture_normalised_z(np.log(block_std(resid, B) + 0.5), block_mean(tex, B))
    nr = outlier_regions(nz, B, thresh=3.8, min_blocks=3, two_sided=True)
    cm = copy_move(gray)
    g = jpeg_grid(gray)
    blk = block_std(gray.astype(np.float32), 8)
    return {
        "ela_top": er[0]["mean_z"] if er else 0.0,
        "ela_area": float(sum(r["area_frac"] for r in er)),
        "ela_p99": float(np.percentile(z, 99)),
        "ela_spread": float(np.std(z)),
        "noise_top": nr[0]["mean_z"] if nr else 0.0,
        "noise_area": float(sum(r["area_frac"] for r in nr)),
        "noise_p99": float(np.percentile(np.abs(nz), 99)),
        "cm_matches": float(cm["matches"]) if cm else 0.0,
        "grid_max": float(max(g["strength_x"], g["strength_y"])),
        "grid_misaligned": float(g["present"] and (g["phase_x"] != 7 or g["phase_y"] != 7)),
        "blockiness_var": float(np.std(np.log(blk + 1))),
    }


def dhash(img_gray: np.ndarray, size: int = 16) -> np.ndarray:
    s = cv2.resize(img_gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    return (s[:, 1:] > s[:, :-1]).flatten()


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray.size else 0.0
