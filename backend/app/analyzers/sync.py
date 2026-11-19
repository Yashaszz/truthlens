"""Audio-visual synchronisation check.

Mouth-region motion (from the video pass) is cross-correlated with the speech energy envelope at lags
of ±0.6 s, restricted to times where a face is visible and speech is present (Whisper segments when
available). A genuine talking-head recording shows a positive correlation peaking near zero lag;
dubbed or lip-synced deepfakes show weak correlation or an offset."""
from __future__ import annotations

import numpy as np

from ..common import AnalysisContext, clamp, fmt_ts


def _smooth(a: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return a
    out = np.convolve(np.nan_to_num(a, nan=0.0), np.ones(k) / k, mode="same")
    out[np.isnan(a)] = np.nan
    return out


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 10:
        return np.nan
    x, y = a[m], b[m]
    if x.std() < 1e-9 or y.std() < 1e-9:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def analyze_sync(ctx: AnalysisContext, ev: dict, video: dict, audio: dict) -> dict | None:
    eid = ev["id"]
    mm = video.get("_mouth_motion")
    fps = video.get("_fps")
    rms_db = audio.get("_rms_db")
    if mm is None or rms_db is None or fps is None:
        return None
    hop_s = audio["_hop"] / 16000
    n = len(mm)
    t = np.arange(n) / fps
    # audio energy per video frame
    idx = np.clip((t / hop_s).astype(int), 0, len(rms_db) - 1)
    span = max(1, int(1 / fps / hop_s))
    lin = 10 ** (rms_db / 20)
    env = np.array([lin[i:i + span].mean() for i in idx])
    # speech mask
    speech = np.zeros(n, bool)
    tr = audio.get("transcript")
    if tr and tr.get("segments"):
        for s in tr["segments"]:
            speech[(t >= s["start"]) & (t <= s["end"])] = True
    else:
        thr = np.percentile(rms_db, 30) + 8
        speech = rms_db[idx] > thr
    face = ~np.isnan(mm)
    valid = face & speech
    summary = {"valid_seconds": round(float(valid.sum() / fps), 2), "face_seconds": round(float(face.sum() / fps), 2),
               "speech_seconds": round(float(speech.sum() / fps), 2)}
    if valid.sum() < 3 * fps:
        reason = "speaker's face not visible during speech" if speech.sum() >= 3 * fps else "too little speech"
        ctx.limit(f"{eid}: audio-visual sync not assessable ({reason}; {summary['valid_seconds']}s usable).")
        summary["assessable"] = False
        summary["reason"] = reason
        return summary

    k = max(1, int(round(fps / 10)))
    m_s = _smooth(np.where(valid, mm, np.nan), k)
    e_s = _smooth(np.where(valid, env, np.nan), k)
    max_lag = int(round(0.6 * fps))
    lags = list(range(-max_lag, max_lag + 1))
    corrs = []
    for L in lags:  # L > 0: audio lags behind video
        if L >= 0:
            c = _corr(m_s[: n - L] if L else m_s, e_s[L:])
        else:
            c = _corr(m_s[-L:], e_s[: n + L])
        corrs.append(c)
    corrs_arr = np.array(corrs, dtype=float)
    if np.all(np.isnan(corrs_arr)):
        summary["assessable"] = False
        return summary
    bi = int(np.nanargmax(corrs_arr))
    best_lag = lags[bi] / fps
    best = float(corrs_arr[bi])
    zero = float(corrs_arr[max_lag]) if not np.isnan(corrs_arr[max_lag]) else 0.0

    # local windows at best lag
    L = lags[bi]
    shifted = np.full(n, np.nan)
    if L >= 0:
        shifted[: n - L] = e_s[L:]
    else:
        shifted[-L:] = e_s[: n + L]
    win = int(4 * fps)
    windows, bad = [], []
    for s0 in range(0, n - win + 1, win // 2):
        c = _corr(m_s[s0:s0 + win], shifted[s0:s0 + win])
        if np.isnan(c):
            continue
        windows.append({"start": round(s0 / fps, 2), "end": round((s0 + win) / fps, 2), "corr": round(c, 3)})
        if c < 0.0:
            bad.append({"start": round(s0 / fps, 2), "end": round((s0 + win) / fps, 2), "score": round(clamp(0.5 - c), 3)})
    merged = []
    for b in bad:
        if merged and b["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = b["end"]
            merged[-1]["score"] = max(merged[-1]["score"], b["score"])
        else:
            merged.append(dict(b))

    step = max(1, n // 400)
    def norm(a):
        a = a[::step]
        mu, sd = np.nanmean(a), np.nanstd(a) + 1e-9
        return [None if np.isnan(v) else round(float((v - mu) / sd), 3) for v in a]
    summary.update({"assessable": True, "best_lag_s": round(best_lag, 3), "best_corr": round(best, 3),
                    "zero_lag_corr": round(zero, 3), "lag_curve": [{"lag": round(l / fps, 3), "corr": None if np.isnan(c) else round(c, 3)}
                                                                  for l, c in zip(lags, corrs)],
                    "windows": windows, "series": {"t_step": step / fps, "mouth": norm(m_s), "audio": norm(e_s)}})

    loc_segments = merged
    if best < 0.12:
        s = clamp(0.5 + (0.12 - best))
        f = ctx.finding("cross-modal", eid, "av-sync", "Weak lip-motion / speech correspondence",
                        f"Mouth movement and speech energy are barely correlated (peak r = {best:.2f} at "
                        f"{best_lag * 1000:+.0f} ms over {summary['valid_seconds']}s of on-screen speech). In genuine "
                        "talking-head footage they move together.",
                        {"type": "segments", "segments": loc_segments or [{"start": 0, "end": round(n / fps, 2)}]},
                        s, 0.35, "av_sync",
                        limitations="Mouth region is located with a coarse face detector; side profiles, beards, "
                                    "masks or off-screen narrators weaken this check.",
                        alternatives=["Voice-over / narrator not shown on screen", "Multiple speakers", "Poor face tracking"])
        ctx.signal("av_sync", "cross-modal", eid, s, 0.35, f"Peak AV correlation {best:.2f}.", [f["id"]],
                   label="Audio-visual sync")
    elif abs(best_lag) > 0.2:
        s = clamp(0.45 + abs(best_lag) * 0.6)
        f = ctx.finding("cross-modal", eid, "av-sync", f"Audio offset of {best_lag * 1000:+.0f} ms",
                        f"Speech energy best matches mouth motion when shifted {best_lag * 1000:+.0f} ms "
                        f"(r = {best:.2f} vs {zero:.2f} at zero lag). Offsets beyond ~200 ms are noticeable and "
                        "suggest the audio was re-attached or dubbed.",
                        {"type": "segments", "segments": loc_segments or [{"start": 0, "end": round(n / fps, 2)}]},
                        s, 0.45, "av_sync", limitations="Some broadcast/encoding pipelines introduce constant offsets.",
                        alternatives=["Encoding/streaming delay", "Bluetooth capture latency"])
        ctx.signal("av_sync", "cross-modal", eid, s, 0.45, f"Best lag {best_lag * 1000:+.0f} ms (r={best:.2f}).",
                   [f["id"]], label="Audio-visual sync")
    else:
        fids = []
        if merged:
            f = ctx.finding("cross-modal", eid, "av-sync", f"Local lip-sync breaks in {len(merged)} window(s)",
                            "Overall sync is good, but correlation turns negative in: "
                            + ", ".join(f"{fmt_ts(m['start'])}–{fmt_ts(m['end'])}" for m in merged[:5])
                            + ". Localised lip-sync deepfakes or inserted audio show this pattern.",
                            {"type": "segments", "segments": merged}, 0.45, 0.3, "av_sync",
                            alternatives=["Speaker turned away / occluded", "Pause or laughter"])
            fids.append(f["id"])
        ctx.signal("av_sync", "cross-modal", eid, 0.3 if merged else 0.15, 0.4,
                   f"Lip motion matches speech (r={best:.2f}, lag {best_lag * 1000:+.0f} ms).", fids,
                   label="Audio-visual sync")
    return summary
