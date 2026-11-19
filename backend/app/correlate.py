"""Cross-modal correlation: links findings across media channels and evidence items.

1. Temporal convergence: flagged video frames, audio segments and sync breaks that overlap in time.
2. Channel pattern: how face, voice and lip-sync results relate (e.g. authentic face + synthetic voice = dubbing).
3. Provenance: an uploaded image that is a frame of an uploaded video.
4. Claim vs media: text findings that coincide with media findings on the same evidence."""
from __future__ import annotations

import numpy as np

from .common import AnalysisContext, clamp, fmt_ts


def _intervals(f: dict) -> list[tuple[float, float]]:
    loc = f.get("location") or {}
    t = loc.get("type")
    if t == "frames":
        return [(fr["t"] - 0.75, fr["t"] + 0.75) for fr in loc.get("frames", [])]
    if t == "segments":
        return [(s["start"], s["end"]) for s in loc.get("segments", [])]
    if t == "timestamps":
        return [(x - 1.0, x + 1.0) for x in loc.get("times", [])]
    return []


def _group(f: dict) -> str:
    if f["modality"] == "cross-modal":
        return "sync"
    return f["modality"]


def correlate(ctx: AnalysisContext, evidence: list[dict], summaries: dict[str, dict]) -> list[dict]:
    links: list[dict] = []
    sig = {}
    for s in ctx.signals:
        sig.setdefault((s["evidence_id"], s["detector"]), s)

    # ---------- 1. temporal convergence within each video -------------------------
    for ev in evidence:
        if ev["modality"] != "video":
            continue
        items = []
        for f in ctx.findings:
            if f["evidence_id"] != ev["id"] or f["detector"] in ("ela",):
                continue
            for a, b in _intervals(f):
                if b - a > 6.0:
                    continue  # long spans (e.g. a whole-clip freeze) overlap everything and prove nothing
                items.append((max(0.0, a), b, _group(f), f))
        if not items:
            continue
        items.sort(key=lambda x: x[0])
        clusters, cur = [], [items[0]]
        for it in items[1:]:
            if it[0] <= max(c[1] for c in cur):
                cur.append(it)
            else:
                clusters.append(cur)
                cur = [it]
        clusters.append(cur)
        for cl in clusters:
            groups = {c[2] for c in cl}
            if len(groups) < 2:
                continue
            fids = sorted({c[3]["id"] for c in cl})
            fs = [next(f for f in ctx.findings if f["id"] == i) for i in fids]
            start, end = min(c[0] for c in cl), max(c[1] for c in cl)
            p_none = np.prod([1 - f["score"] * f["confidence"] for f in fs])
            score = clamp(0.45 + 0.5 * (1 - p_none))
            conf = clamp(np.mean([f["confidence"] for f in fs]) + 0.1)
            names = ", ".join(f"{f['modality']}: {f['title']}" for f in fs[:4])
            f = ctx.finding("cross-modal", ev["id"], "convergence",
                            f"Independent indicators converge at {fmt_ts(start)}–{fmt_ts(end)}",
                            f"{len(groups)} independent channels ({', '.join(sorted(groups))}) flag the same time span: {names}. "
                            "Agreement between unrelated detectors makes coincidence less likely.",
                            {"type": "segments", "segments": [{"start": round(start, 2), "end": round(end, 2)}]},
                            score, conf, "cross_modal", related=fids,
                            limitations="Detectors can share failure causes (e.g. heavy compression affects both face and audio models).",
                            alternatives=["A single low-quality passage triggering several detectors"])
            for o in fs:
                o["related"] = sorted(set(o["related"]) | {f["id"]})
            ctx.signal("cross_modal", "cross-modal", ev["id"], score, conf,
                       f"{len(groups)} channels agree at {fmt_ts(start)}.", [f["id"], *fids], label="Temporal convergence")
            links.append({"type": "temporal-convergence", "effect": "strengthens", "evidence_ids": [ev["id"]],
                          "finding_ids": [f["id"], *fids], "title": f["title"], "description": f["description"],
                          "window": [round(start, 2), round(end, 2)]})

    # ---------- 2. channel pattern per video --------------------------------------
    for ev in evidence:
        if ev["modality"] != "video":
            continue
        face = sig.get((ev["id"], "face_deepfake_model"))
        voice = sig.get((ev["id"], "audio_spoof_model"))
        sync = sig.get((ev["id"], "av_sync"))
        if not (face or voice):
            continue
        fsc = face["score"] if face else None
        vsc = voice["score"] if voice else None
        sync_bad = bool(sync and sync["score"] >= 0.45)
        pattern = None
        if fsc is not None and vsc is not None and fsc >= 0.6 and vsc >= 0.6:
            pattern = ("both-synthetic", "strengthens", "Face and voice both show synthetic indicators",
                       "Visual and audio channels independently indicate generation, consistent with a fully synthetic "
                       "talking-head deepfake.")
        elif vsc is not None and vsc >= 0.6 and (fsc is None or fsc < 0.45):
            pattern = ("voice-only", "context", "Synthetic voice over apparently authentic video",
                       "The voice channel is flagged while the face is not"
                       + (" and lip-sync is poor" if sync_bad else "")
                       + ". This pattern fits dubbing or voice cloning laid over real footage.")
        elif fsc is not None and fsc >= 0.6 and (vsc is None or vsc < 0.45):
            pattern = ("face-only", "context", "Manipulated face with natural-sounding voice",
                       "The face channel is flagged while the voice is not"
                       + (", and lip-sync is poor" if sync_bad else "")
                       + ". This fits a face swap or lip-sync reenactment using the original or a real voice.")
        elif fsc is not None and vsc is not None and fsc < 0.4 and vsc < 0.4 and not sync_bad:
            pattern = ("consistent", "weakens", "Face, voice and lip-sync mutually consistent",
                       "Neither the face nor the voice classifier is triggered and lip motion agrees with speech, "
                       "so the channels corroborate each other.")
        if pattern:
            kind, effect, title, desc = pattern
            fids = [x for s in (face, voice, sync) if s for x in s["finding_ids"]]
            links.append({"type": f"channel-pattern:{kind}", "effect": effect, "evidence_ids": [ev["id"]],
                          "finding_ids": fids, "title": title, "description": desc,
                          "scores": {"face": fsc, "voice": vsc, "sync": sync["score"] if sync else None}})
            if kind == "both-synthetic":
                ctx.signal("cross_modal", "cross-modal", ev["id"], clamp(max(fsc, vsc)), 0.5, desc, fids,
                           label="Channel agreement")
            elif kind == "consistent":
                ctx.signal("cross_modal", "cross-modal", ev["id"], 0.15, 0.4, desc, [], label="Channel agreement")

    # ---------- 3. provenance: image ↔ video frames --------------------------------
    images = [e for e in evidence if e["modality"] == "image" and summaries.get(e["id"], {}).get("dhash")]
    videos = [e for e in evidence if e["modality"] == "video" and summaries.get(e["id"], {}).get("_hashes")]
    for im in images:
        h = np.array(summaries[im["id"]]["dhash"], bool)
        for vd in videos:
            best = min(((float(np.mean(h != vh)), t) for t, vh in summaries[vd["id"]]["_hashes"]), default=None)
            if best and best[0] < 0.15:
                links.append({"type": "provenance", "effect": "context", "evidence_ids": [im["id"], vd["id"]],
                              "finding_ids": [], "title": f"{im['id']} matches a frame of {vd['id']}",
                              "description": f"Perceptual hash of {im['filename']} is {100 * (1 - best[0]):.0f}% similar to "
                                             f"the frame at {fmt_ts(best[1])} in {vd['filename']}: the still likely "
                                             "comes from (or was used to make) this video. Findings on one should be read with the other."})

    # ---------- 4. text claims ↔ media findings ------------------------------------
    text_f = [f for f in ctx.findings if f["modality"] == "text" and f["evidence_id"]]
    for tf in text_f:
        media_f = [f for f in ctx.findings if f["evidence_id"] == tf["evidence_id"] and f["modality"] in ("video", "audio", "image")
                   and f["score"] >= 0.55]
        if media_f:
            links.append({"type": "claim-vs-media", "effect": "strengthens", "evidence_ids": [tf["evidence_id"]],
                          "finding_ids": [tf["id"], *[f["id"] for f in media_f[:4]]],
                          "title": f"Context problem and media indicators on {tf['evidence_id']}",
                          "description": f"“{tf['title']}” co-occurs with {len(media_f)} media-level indicator(s) "
                                         f"({', '.join(f['title'] for f in media_f[:3])}). Misleading context plus "
                                         "technical anomalies is a stronger combined signal than either alone."})
            tf["related"] = sorted(set(tf["related"]) | {f["id"] for f in media_f})

    # ---------- 5. metadata dates disagree across evidence -------------------------
    dated = [(e["id"], summaries.get(e["id"], {}).get("capture_time") or summaries.get(e["id"], {}).get("creation_time"))
             for e in evidence]
    dated = [(i, d) for i, d in dated if d]
    if len(dated) >= 2:
        import datetime as dt
        parsed = []
        for i, d in dated:
            try:
                parsed.append((i, dt.datetime.fromisoformat(str(d).replace("Z", "+00:00")).replace(tzinfo=None)))
            except Exception:
                pass
        if len(parsed) >= 2:
            span = max(p[1] for p in parsed) - min(p[1] for p in parsed)
            if span.days >= 2:
                links.append({"type": "date-spread", "effect": "context", "evidence_ids": [p[0] for p in parsed],
                              "finding_ids": [], "title": f"Evidence items dated {span.days} days apart",
                              "description": "Metadata dates: " + ", ".join(f"{i} {d:%Y-%m-%d}" for i, d in parsed)
                                             + ". If these are presented as the same event, verify the timeline."})
    return links
