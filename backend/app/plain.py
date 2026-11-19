"""Plain-language layer: turns findings, signals and fusion output into sentences a non-specialist can read.
Used by the API (case page) and the HTML report. Technical detail stays available alongside it."""
from __future__ import annotations


def _t(sec) -> str:
    sec = max(0.0, float(sec or 0))
    m, s = divmod(int(round(sec)), 60)
    return f"{m}:{s:02d}"


def _times(f: dict, limit: int = 4) -> str:
    loc = f.get("location") or {}
    ts = []
    if loc.get("type") == "frames":
        ts = [_t(x["t"]) for x in loc.get("frames", [])]
    elif loc.get("type") == "segments":
        ts = [_t(s["start"]) if _t(s["start"]) == _t(s["end"]) else f"{_t(s['start'])}–{_t(s['end'])}"
              for s in loc.get("segments", [])]
    elif loc.get("type") == "timestamps":
        ts = [_t(x) for x in loc.get("times", [])]
    if not ts:
        return ""
    more = f" and {len(ts) - limit} more" if len(ts) > limit else ""
    return " (at " + ", ".join(ts[:limit]) + more + ")"


PLAIN = {
    "generator_metadata": lambda f: "The file's own metadata says it was made with an AI generation tool.",
    "ai_image_model": lambda f: "An AI-image detector thinks this picture looks computer-generated.",
    "ai_ensemble": lambda f: f"This picture was very likely made by an AI image generator ({f['score']:.0%}).",
    "ai_tiles": lambda f: "Part of this photo looks AI-generated while the rest looks real, a sign of AI editing (generative fill or inpainting).",
    "ai_frames": lambda f: f"The video frames carry AI-generator fingerprints ({f['score']:.0%}), so the footage itself looks AI-generated.",
    "trufor": lambda f: "A forgery detector found an edited region in the picture and marks where it is.",
    "metadata_deep": lambda f: f["description"].split(". ")[0] + ".",
    "face_deepfake_model": lambda f: ("A face looks digitally altered" + _times(f) + ".") if f["modality"] != "image"
    else "The face in this photo looks digitally altered.",
    "face_sharpness": lambda f: "The face is noticeably blurrier than its surroundings, which is common when a face is swapped in.",
    "ela": lambda f: "Some areas were compressed differently from the rest of the picture. This often happens when "
                     "something is pasted in or retouched.",
    "noise_residual": lambda f: "The natural grain of the camera doesn't match in some areas, as if they came from a "
                                "different source or were smoothed over.",
    "copy_move": lambda f: "Part of the picture appears to have been copied and pasted somewhere else in the same picture.",
    "jpeg_grid": lambda f: "The file shows signs of being saved, cropped and saved again.",
    "exif_software": lambda f: "The file was saved by photo-editing software after it was taken.",
    "exif_missing": lambda f: "The photo carries no camera information, so we can't confirm which device took it or when.",
    "exif_dates": lambda f: "The photo was modified at a different time from when it was taken.",
    "temporal_cuts": lambda f: "The video jumps abruptly between shots" + _times(f) + ".",
    "frozen_frames": lambda f: "The picture freezes or repeats" + _times(f) + ", which can hide removed footage.",
    "video_container": lambda f: "The video file was re-encoded by editing or conversion software, so it isn't a camera original.",
    "audio_spoof_model": lambda f: "Parts of the voice sound machine-generated" + _times(f) + ".",
    "digital_silence": lambda f: "There are perfectly silent gaps" + _times(f) + ". Real microphones are never fully silent, "
                                 "so this suggests cut-and-paste editing.",
    "noise_floor_jumps": lambda f: "The background sound changes suddenly" + _times(f) + ", as if pieces of different "
                                   "recordings were joined together.",
    "audio_bandwidth": lambda f: "The sound is missing high frequencies it should have, which some voice generators leave behind.",
    "pitch_smoothness": lambda f: "The voice's tone is unusually flat and even, which some synthetic voices sound like.",
    "av_sync": lambda f: "The lip movements don't line up with the voice" + _times(f) + ".",
    "quote_check": lambda f: ("The quote in the caption is not actually said in the recording."
                              if "not found" in f["title"].lower() else
                              "The quote in the caption only partly matches what is said in the recording."),
    "topic_overlap": lambda f: "The caption talks about something different from what is said in the recording.",
    "date_consistency": lambda f: ("The media is older than the caption suggests." if "recent" in f["title"].lower()
                                   else "The date in the caption doesn't match the file's own date."),
    "transcript_match": lambda f: "The transcript provided doesn't match what is actually said in the recording.",
    "sensational_language": lambda f: "The caption uses urgent, sensational wording often seen in misleading posts.",
    "cross_modal": lambda f: "Several independent checks flag the same moment" + _times(f) + ", which makes coincidence less likely.",
}

CLEAN = {
    "copy_move": "No copied-and-pasted areas inside the picture",
    "ela": "Compression is consistent across the picture",
    "noise_residual": "Camera grain is consistent across the picture",
    "ai_image_model": "The AI-image detector did not flag it",
    "face_deepfake_model": "Faces were not flagged as altered",
    "audio_spoof_model": "The voice was not flagged as machine-generated",
    "noise_floor_jumps": "Background sound is continuous",
    "temporal_cuts": "The video plays continuously without hidden cuts",
    "av_sync": "Lip movements match the voice",
    "quote_check": "The quoted words are really said in the recording",
    "date_consistency": "Dates in the caption match the file",
    "topic_overlap": "The caption is about the same subject as the speech",
    "transcript_match": "The supplied transcript matches the audio",
}

HEADLINE = {
    "strong": "Strong signs of manipulation",
    "indicators": "Signs of possible manipulation",
    "inconclusive": "No clear answer: a person needs to look at this",
    "none": "No clear signs of manipulation",
}
HEADLINE_SUB = {
    "strong": "Several reliable checks point to this material having been altered or generated.",
    "indicators": "Some checks found problems. They are worth a closer look, but they are not proof on their own.",
    "inconclusive": "The checks either found little or disagree with each other, so the computer can't decide.",
    "none": "Nothing stood out, but this does not prove the material is genuine.",
}


def strength(score: float) -> str:
    return "Strong" if score >= 0.7 else "Moderate" if score >= 0.55 else "Weak"


def reliability_word(conf: float) -> str:
    return "reliable check" if conf >= 0.5 else "fairly reliable check" if conf >= 0.35 else "rough check"


def finding_plain(f: dict) -> str:
    fn = PLAIN.get(f["detector"])
    try:
        return fn(f) if fn else f["title"]
    except Exception:
        return f["title"]


def summarize(case: dict) -> dict | None:
    r = case.get("results")
    if not r:
        return None
    names = {e["id"]: e["filename"] for e in case["evidence"]}
    kinds = {e["id"]: e["modality"] for e in case["evidence"]}
    o = r["fusion"]["overall"]
    lo, hi = o["interval"]
    width = hi - lo
    certainty = ("fairly certain" if width < 0.35 else "moderately certain" if width < 0.55 else "not very certain")
    agree = o.get("agreement")
    agreement = ("most checks agree" if (agree or 0) >= 0.7 else
                 "the checks partly disagree" if (agree or 0) >= 0.45 else "the checks disagree with each other")

    for f in r["findings"]:
        f["plain"] = finding_plain(f)
        f["strength"] = strength(f["score"])
        f["reliability_word"] = reliability_word(f["confidence"])

    key = [f for f in r["findings"] if f["score"] >= 0.5 and f["confidence"] >= 0.3]
    seen, found = set(), []
    for f in sorted(key, key=lambda f: -f["score"] * f["confidence"]):
        k = (f["evidence_id"], f["detector"])
        if k in seen:
            continue
        seen.add(k)
        where = names.get(f["evidence_id"], "the case")
        found.append({"text": f["plain"], "file": where, "evidence_id": f["evidence_id"], "finding_id": f["id"],
                      "strength": f["strength"]})
    minor = [f for f in r["findings"] if f not in key]

    clean, cseen = [], set()
    for s in r["signals"]:
        if s["score"] < 0.3 and s["reliability"] >= 0.3 and s["detector"] in CLEAN:
            k = (s["evidence_id"], s["detector"])
            if k not in cseen:
                cseen.add(k)
                clean.append({"text": CLEAN[s["detector"]], "file": names.get(s["evidence_id"], "the case"),
                              "evidence_id": s["evidence_id"]})

    per_ev = {}
    for eid, v in r["fusion"]["by_evidence"].items():
        fl = [f for f in key if f["evidence_id"] == eid]
        verdict = {"strong": "Likely altered", "indicators": "Suspicious", "inconclusive": "Unclear",
                   "none": "Nothing found"}[v["band"]]
        if fl:
            sentence = fl[0]["plain"] if len(fl) == 1 else f"{len(fl)} problems found. Main one: {fl[0]['plain'][0].lower()}{fl[0]['plain'][1:]}"
        else:
            sentence = "No significant problems found by the checks that could run on this file."
        per_ev[eid] = {"verdict": verdict, "band": v["band"], "sentence": sentence, "flags": len(fl),
                       "score": v["score"], "kind": kinds.get(eid)}

    connections = []
    for l in r.get("links", []):
        t = l["type"]
        if t == "provenance":
            text = l["description"].split(":")[0] + "."
        elif t.startswith("channel-pattern"):
            text = l["title"] + ". " + l["description"]
        else:
            text = l["title"] + "."
        connections.append({"text": text, "effect": l["effect"], "evidence_ids": l["evidence_ids"]})

    global_lims = 4  # first four limitations are the standing caveats
    not_checked = r["limitations"][global_lims:]

    headline, subline, band = HEADLINE[o["band"]], HEADLINE_SUB[o["band"]], o["band"]
    confidence_text = f"We are {certainty} about this, and {agreement}."
    th = r.get("threats") or {}
    v = th.get("verdict") or {}
    if v.get("confidence") is not None:
        conf = v["confidence"]
        headline = v["label"]
        band = ("strong" if v.get("fake") and conf >= 0.8 else "indicators" if v.get("fake") else
                "none" if conf >= 0.6 and not v.get("lean") else "inconclusive" if v.get("lean") else "none")
        where = names.get(v.get("evidence_id"))
        if where and len(where) > 42:
            where = where[:30] + "…" + where[-8:]
        detected = [m["name"] for it in th.get("items", {}).values() for m in it["matrix"] if m["status"] == "detected"]
        if v.get("fake"):
            subline = (f"{conf:.0%} likely, based on {where}." if where else f"{conf:.0%} likely.") + \
                      (f" Threats detected: {', '.join(dict.fromkeys(detected))}." if detected else "") + \
                      (f" {v['disagreement']}" if v.get("disagreement") else "")
        elif v.get("lean"):
            subline = f"The evidence leans this way ({conf:.0%}). It's a close call, so the specific checks below matter."
        else:
            subline = f"{conf:.0%} likely genuine: none of the threat checks found manipulation."
        confidence_text = ("Probabilities come from detectors calibrated on labelled public benchmarks "
                           "(see the technical appendix for measured accuracy).")
        for eid, it in th.get("items", {}).items():
            iv = it["verdict"]
            if eid in per_ev and iv.get("confidence") is not None:
                per_ev[eid]["verdict"] = f"{iv['label']} · {iv['confidence']:.0%}"
                per_ev[eid]["band"] = ("strong" if iv.get("fake") and iv["confidence"] >= 0.8 else "indicators" if iv.get("fake")
                                       else "inconclusive" if iv.get("lean") else "none")

    return {
        "headline": headline,
        "subline": subline,
        "band": band,
        "verdict": v or None,
        "confidence_text": confidence_text,
        "driven_by": names.get(o.get("driven_by")) if o.get("driven_by") else None,
        "found": found[:6],
        "minor_count": len(minor),
        "looked_fine": clean[:8],
        "per_evidence": per_ev,
        "connections": connections,
        "next_steps": [x["check"] for x in r.get("recommendations", [])][:5],
        "not_checked": not_checked,
        "caveat": "This is an automated screening to guide a human examiner. A score is an indicator, not proof.",
    }
