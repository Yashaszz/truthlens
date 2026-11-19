"""Audio & voice analysis: wav2vec2 spoof classifier per window, MFCC/ZCR/spectral features,
splice heuristics (digital silence, noise-floor jumps), bandwidth, pitch smoothness, Whisper transcript."""
from __future__ import annotations

from pathlib import Path

import cv2
import librosa
import numpy as np

from .. import media, models
from ..common import AnalysisContext, clamp, fmt_ts
from ..config import AUDIO_HOP_S, AUDIO_MAX_SECONDS, AUDIO_WINDOW_S

SR = 16000


def _merge_segments(times: list[tuple[float, float, float]], gap: float = 0.5) -> list[dict]:
    out = []
    for s, e, p in sorted(times):
        if out and s <= out[-1]["end"] + gap:
            out[-1]["end"] = max(out[-1]["end"], e)
            out[-1]["score"] = max(out[-1]["score"], p)
        else:
            out.append({"start": s, "end": e, "score": p})
    for o in out:
        o["start"], o["end"], o["score"] = round(o["start"], 2), round(o["end"], 2), round(o["score"], 3)
    return out


def analyze_audio(ctx: AnalysisContext, ev: dict, src: Path, *, modality: str = "audio",
                  label: str = "audio") -> dict:
    eid = ev["id"]
    wav = ctx.work_dir / f"{eid}_{label}_16k.wav"
    if not media.to_wav(src, wav, SR, AUDIO_MAX_SECONDS):
        ctx.limit(f"{eid}: no decodable audio track.")
        return {"error": "no audio"}
    y, _ = librosa.load(str(wav), sr=SR, mono=True)
    dur = len(y) / SR
    summary: dict = {"duration": round(dur, 2), "artifacts": {}, "_wav": str(wav)}
    if dur < 1.0:
        ctx.limit(f"{eid}: audio shorter than 1 s; audio analysis skipped.")
        return summary
    if dur >= AUDIO_MAX_SECONDS - 0.5:
        ctx.limit(f"{eid}: only the first {AUDIO_MAX_SECONDS}s of audio were analysed.")

    # ---------------- frame features ------------------------------------------
    hop = 160  # 10 ms
    rms = librosa.feature.rms(y=y, frame_length=400, hop_length=hop)[0]
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=400, hop_length=hop)[0]
    flat = librosa.feature.spectral_flatness(y=y, n_fft=512, hop_length=hop)[0]
    cent = librosa.feature.spectral_centroid(y=y, sr=SR, n_fft=512, hop_length=hop)[0]
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=20, n_fft=512, hop_length=hop)
    rms_db = 20 * np.log10(rms + 1e-7)
    speech_thr = max(np.percentile(rms_db, 30) + 8, -45)
    voiced_mask = rms_db > speech_thr
    summary["speech_ratio"] = round(float(voiced_mask.mean()), 3)

    # downsampled curves for the UI (≈ 4 points/s)
    step = 25
    n = len(rms) // step
    def ds(a):
        return [round(float(v), 4) for v in a[: n * step].reshape(n, step).mean(axis=1)]
    summary["curves"] = {"t_step": step * hop / SR, "rms_db": ds(rms_db), "zcr": ds(zcr),
                         "flatness": ds(flat), "centroid": ds(cent / 1000),
                         "mfcc_delta": ds(np.abs(np.diff(mfcc, axis=1, prepend=mfcc[:, :1])).mean(axis=0))}

    # ---------------- spoof classifier per window -------------------------------
    win, hopw = int(AUDIO_WINDOW_S * SR), int(AUDIO_HOP_S * SR)
    starts = list(range(0, max(1, len(y) - win + 1), hopw)) or [0]
    chunks, wins = [], []
    for s in starts:
        seg = y[s:s + win]
        fr = voiced_mask[s // hop:(s + win) // hop]
        if len(seg) < SR or (fr.size and fr.mean() < 0.15):
            continue  # skip silence: classifier output on silence is meaningless
        chunks.append(seg.astype(np.float32))
        wins.append((s / SR, min(dur, (s + win) / SR)))
    probs = models.audio_spoof_probs(chunks) if chunks else []
    window_scores = []
    if chunks and probs is None:
        ctx.limit(f"Audio spoof model unavailable ({models.model_error('audio_spoof')}).")
    elif probs:
        window_scores = [{"start": round(a, 2), "end": round(b, 2), "p_fake": round(p, 4)} for (a, b), p in zip(wins, probs)]
        arr = np.array(probs)
        agg = float(0.5 * np.median(arr) + 0.5 * np.percentile(arr, 80))
        segs = _merge_segments([(a, b, p) for (a, b), p in zip(wins, probs) if p >= 0.65])
        rel = 0.5 * min(1.0, len(chunks) / 5) * (0.6 if summary["speech_ratio"] < 0.2 else 1.0)
        if np.mean((arr < 0.02) | (arr > 0.98)) > 0.8:
            rel *= 0.7  # saturated (near 0/1) outputs: the classifier is over-confident here
            ctx.limit(f"{eid}: voice-spoof classifier outputs are saturated (near 0 or 1), a sign of over-confidence "
                      "on out-of-distribution audio; its weight was reduced.")
        flagged = arr[arr >= 0.65]
        if flagged.size:
            # localised manipulation (e.g. one cloned sentence) must not be hidden by the median of clean windows
            frac = flagged.size / arr.size
            agg = max(agg, float(flagged.mean()) * (0.5 + 0.5 * frac))
        if segs:
            f = ctx.finding(modality, eid, "voice-synthesis",
                            f"Synthetic-speech indicators in {len(segs)} segment(s)",
                            f"The wav2vec2 anti-spoofing classifier ({models.MODELS['audio_spoof']}) scored "
                            f"{sum(p >= 0.65 for p in probs)}/{len(probs)} speech windows ≥65% fake "
                            f"(median {np.median(arr):.0%}, peak {arr.max():.0%}). Segments: "
                            + ", ".join(f"{fmt_ts(s['start'])}–{fmt_ts(s['end'])}" for s in segs[:6]) + ".",
                            {"type": "segments", "segments": segs}, float(flagged.mean()), rel, "audio_spoof_model",
                            limitations="Trained on specific TTS/VC systems; phone codecs, music, noise and "
                                        "non-English speech raise false positives. Unseen cloning tools may evade it.",
                            alternatives=["Low-bitrate / telephone compression", "Background music", "Studio processing (autotune, denoise)"])
            ctx.signal("audio_spoof_model", modality, eid, agg, rel,
                       f"Aggregated P(fake) = {agg:.2f} over {len(probs)} speech windows.", [f["id"]],
                       label="Voice spoof classifier (wav2vec2)")
        else:
            ctx.signal("audio_spoof_model", modality, eid, agg, rel,
                       f"Aggregated P(fake) = {agg:.2f}; no window above 0.65.", label="Voice spoof classifier (wav2vec2)")
    summary["window_scores"] = window_scores
    if not chunks:
        ctx.limit(f"{eid}: little or no speech detected; voice analysis limited.")

    # ---------------- digital silence (exact zeros inside the recording) -------
    zero = np.abs(y) < 1e-5
    runs, start = [], None
    for k in range(0, len(zero), 80):  # 5 ms resolution
        v = zero[k:k + 80].all()
        if v and start is None:
            start = k
        elif not v and start is not None:
            if (k - start) / SR >= 0.15 and start > SR * 0.3 and k < len(y) - SR * 0.3:
                runs.append((start / SR, k / SR))
            start = None
    if runs:
        segs = [{"start": round(a, 2), "end": round(b, 2)} for a, b in runs]
        f = ctx.finding(modality, eid, "splicing", f"{len(runs)} digital-silence gap(s) inside recording",
                        "Stretches of exact digital zero appear mid-recording at "
                        + ", ".join(f"{fmt_ts(a)}" for a, _ in runs[:6]) + ". Real microphones always record a noise "
                        "floor; perfect silence is typical of cut-and-paste editing.",
                        {"type": "segments", "segments": segs}, 0.55, 0.45, "digital_silence",
                        alternatives=["Noise gate / voice-activity gating in a calling app"])
        ctx.signal("digital_silence", modality, eid, 0.55, 0.45, f"{len(runs)} exact-zero gaps.", [f["id"]],
                   label="Digital silence gaps")

    # ---------------- noise-floor discontinuities --------------------------------
    sec = int(SR / hop)  # frames per second
    floors = []
    for k in range(0, len(rms_db) - sec, sec // 2):
        floors.append((k * hop / SR, float(np.percentile(rms_db[k:k + sec], 10))))
    jumps = []
    for (t1, a), (t2, b) in zip(floors, floors[2:]):
        if abs(a - b) > 12 and min(a, b) > -75:
            jumps.append(round(t2, 2))
    dedup = []
    for t in jumps:
        if not dedup or t - dedup[-1] > 2:
            dedup.append(t)
    summary["noise_floor"] = [{"t": round(t, 2), "db": round(v, 1)} for t, v in floors]
    if dedup:
        s = clamp(0.35 + 0.05 * len(dedup), 0.35, 0.6)
        f = ctx.finding(modality, eid, "splicing", f"{len(dedup)} background-noise discontinuit(ies)",
                        "The background noise floor jumps by >12 dB at " + ", ".join(fmt_ts(t) for t in dedup[:6])
                        + ". Audio recorded in one take keeps a steady room tone; jumps suggest segments joined "
                        "from different recordings.", {"type": "timestamps", "times": dedup}, s, 0.35,
                        "noise_floor_jumps", alternatives=["Change of environment while recording", "Automatic gain control"])
        ctx.signal("noise_floor_jumps", modality, eid, s, 0.35, f"{len(dedup)} noise-floor jumps.", [f["id"]],
                   label="Noise-floor continuity")
    else:
        ctx.signal("noise_floor_jumps", modality, eid, 0.15, 0.3, "Background noise floor is continuous.",
                   label="Noise-floor continuity")

    # ---------------- bandwidth (native sample rate) -----------------------------
    try:
        nat = ctx.work_dir / f"{eid}_{label}_native.wav"
        if media.to_wav_native(src, nat, 60):
            yn, srn = librosa.load(str(nat), sr=None, mono=True)
            S = np.abs(librosa.stft(yn[: srn * 60], n_fft=2048)) ** 2
            spec = 10 * np.log10(S.mean(axis=1) + 1e-12)
            freqs = librosa.fft_frequencies(sr=srn, n_fft=2048)
            above = np.where(spec > spec.max() - 70)[0]
            cutoff = float(freqs[above.max()]) if above.size else 0.0
            summary["bandwidth"] = {"sample_rate": int(srn), "effective_cutoff_hz": round(cutoff)}
            if srn >= 32000 and cutoff < 0.45 * srn / 2 and cutoff > 0:
                f = ctx.finding(modality, eid, "voice-synthesis", "Band-limited audio in a high-rate file",
                                f"Energy stops at ≈{cutoff / 1000:.1f} kHz although the file is sampled at {srn / 1000:.0f} kHz. "
                                "Many TTS/voice-conversion vocoders produce 16–24 kHz audio that is later up-sampled.",
                                {"type": "global"}, 0.4, 0.3, "audio_bandwidth",
                                alternatives=["Lossy codec low-pass (MP3/AAC at low bitrate)", "Telephone recording"])
                ctx.signal("audio_bandwidth", modality, eid, 0.4, 0.3, f"Cutoff {cutoff:.0f} Hz at {srn} Hz.",
                           [f["id"]], label="Spectral bandwidth")
            else:
                ctx.signal("audio_bandwidth", modality, eid, 0.2, 0.25, f"Cutoff {cutoff:.0f} Hz consistent with {srn} Hz.",
                           label="Spectral bandwidth")
    except Exception as e:  # pragma: no cover
        ctx.limit(f"{eid}: bandwidth analysis failed ({e}).")

    # ---------------- pitch smoothness (prosody) ---------------------------------
    try:
        f0 = librosa.yin(y, fmin=70, fmax=400, sr=SR, frame_length=1024, hop_length=320)
        e = librosa.feature.rms(y=y, frame_length=1024, hop_length=320)[0][: len(f0)]
        v = f0[: len(e)][20 * np.log10(e + 1e-7) > speech_thr]
        if v.size > 50:
            semis = 12 * np.log2(v / np.median(v))
            jitter = float(np.median(np.abs(np.diff(semis))))
            spread = float(np.std(semis))
            summary["prosody"] = {"f0_median": round(float(np.median(v)), 1), "jitter_semitones": round(jitter, 3),
                                  "range_semitones": round(spread, 2)}
            if spread < 1.2 and jitter < 0.15:
                f = ctx.finding(modality, eid, "voice-synthesis", "Unusually flat, smooth intonation",
                                f"Pitch varies only {spread:.1f} semitones (SD) with micro-jitter {jitter:.2f}. Natural "
                                "speech usually shows more variation; some TTS voices are over-smooth.",
                                {"type": "global"}, 0.4, 0.25, "pitch_smoothness",
                                alternatives=["Monotone reading style", "Pitch-correction processing"])
                ctx.signal("pitch_smoothness", modality, eid, 0.4, 0.25, "Over-smooth prosody.", [f["id"]],
                           label="Prosody / pitch")
            else:
                ctx.signal("pitch_smoothness", modality, eid, 0.2, 0.2, f"Pitch range {spread:.1f} st, natural.",
                           label="Prosody / pitch")
    except Exception:
        pass

    # ---------------- spectrogram artifact ---------------------------------------
    M = librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=SR, n_mels=128, n_fft=1024, hop_length=hop), ref=np.max)
    img = np.clip((M + 80) / 80, 0, 1)[::-1]
    img = cv2.applyColorMap((img * 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
    img = cv2.resize(img, (min(2400, max(800, int(dur * 40))), 256), interpolation=cv2.INTER_AREA)
    p, url = ctx.artifact_path(eid, f"{label}_spectrogram.png")
    cv2.imwrite(str(p), img)
    summary["artifacts"]["spectrogram"] = url

    # ---------------- Whisper transcript ----------------------------------------
    tr = models.transcribe(wav)
    if tr is None:
        ctx.limit(f"Whisper transcription unavailable ({models.model_error('whisper')}); text/sync checks limited.")
    else:
        summary["transcript"] = tr
        ctx.log("transcription", f"{eid}: {len(tr['segments'])} segments, language={tr['language']}", model=tr["model"])
    summary["_y"] = y
    summary["_rms_db"] = rms_db
    summary["_hop"] = hop
    return summary
