"""Text & context analysis: compares investigator-supplied captions/claims and text evidence with
Whisper transcripts and media metadata (quotes, topics, dates, supplied transcripts, sensational framing)."""
from __future__ import annotations

import datetime as dt
import re
from difflib import SequenceMatcher

from ..common import AnalysisContext, clamp, fmt_ts

STOP = set("""a an the and or but if then of to in on at by for with from as is are was were be been being it its this that
these those i you he she we they me him her us them my your his our their not no yes do does did have has had will would
can could should may might must shall just so very also than too into over under about after before up down out off again
there here what which who whom whose when where why how all any both each few more most other some such only own same s t
said says say video audio image clip footage photo shows showing shown""".split())
SENSATIONAL = [r"\bbreaking\b", r"share (this )?before", r"before (it'?s|it is) deleted", r"they don'?t want you",
               r"100\s?% (proof|real|true)", r"\bleaked\b", r"\bshocking\b", r"\burgent\b", r"must (watch|see)",
               r"\bexposed\b", r"\bwake up\b", r"mainstream media won'?t", r"\bbanned\b"]
RECENCY = [r"\btoday\b", r"\byesterday\b", r"\bjust now\b", r"\blive\b", r"\bthis morning\b", r"\btonight\b",
           r"\bthis week\b", r"\bhappening now\b"]
MONTHS = "january february march april may june july august september october november december".split()


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def content(s: str) -> set[str]:
    return {w for w in words(s) if w not in STOP and len(w) > 2 and not w.isdigit()}


def strip_subs(s: str) -> str:
    s = re.sub(r"^\s*WEBVTT.*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\d+\s*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}\s*-->\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}.*", "", s)
    return re.sub(r"<[^>]+>", "", s)


def best_match(quote: str, transcript_words: list[dict]) -> tuple[float, float | None, float | None]:
    """Fuzzy-locate a quote in a word-timestamped transcript. Returns (ratio, start, end)."""
    # Word-level (not character-level) alignment: shared function words and letters must not make an
    # invented quote look like a match.
    q = words(quote)
    qn = len(q)
    if not transcript_words or qn == 0:
        return 0.0, None, None
    toks = [re.sub(r"[^a-z0-9']", "", w["w"].lower()) for w in transcript_words]
    best = (0.0, None, None)
    for size in {max(1, int(qn * 0.8)), qn, int(qn * 1.25) + 1}:
        for i in range(0, max(1, len(toks) - size + 1)):
            r = SequenceMatcher(None, q, toks[i:i + size], autojunk=False).ratio()
            if r > best[0]:
                best = (r, transcript_words[i]["start"], transcript_words[min(len(toks), i + size) - 1]["end"])
    return best


def years_in(s: str) -> set[int]:
    return {int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", s)}


def analyze_text(ctx: AnalysisContext, context: str, text_evidence: list[dict], transcripts: list[dict],
                 media_dates: list[dict], case_created: str) -> dict:
    """transcripts: [{evidence_id, transcript}], media_dates: [{evidence_id, kind, when(iso)}]."""
    claims = [{"source": "case context", "evidence_id": None, "text": context}] if context.strip() else []
    supplied_transcripts = []
    for t in text_evidence:
        body = t["content"]
        if t["filename"].lower().endswith((".srt", ".vtt")) or "-->" in body or "transcript" in t["filename"].lower():
            supplied_transcripts.append({**t, "clean": strip_subs(body)})
        else:
            claims.append({"source": t["filename"], "evidence_id": t["id"], "text": body})
    summary: dict = {"claims": [{"source": c["source"], "evidence_id": c["evidence_id"], "chars": len(c["text"])} for c in claims],
                     "quotes": [], "dates": [], "transcript_checks": []}
    all_words = []
    for tr in transcripts:
        for seg in tr["transcript"].get("segments", []):
            for w in seg.get("words", []):
                all_words.append({**w, "evidence_id": tr["evidence_id"]})
    full_transcript = " ".join(tr["transcript"].get("text", "") for tr in transcripts)

    if not claims and not supplied_transcripts:
        ctx.limit("No captions, claims or text evidence supplied; text & context analysis limited to transcripts.")

    # ---------------- quotes vs transcript ----------------------------------------
    for c in claims:
        quotes = re.findall(r"[\"“”]([^\"“”]{8,400})[\"“”]", c["text"]) + re.findall(r"[‘’]([^‘’]{12,400})[‘’]", c["text"])
        for q in quotes:
            if not all_words:
                summary["quotes"].append({"quote": q, "status": "unverifiable"})
                ctx.limit("Quoted statements could not be checked: no speech transcript available.")
                continue
            ratio, s, e = best_match(q, all_words)
            ev_id = all_words[0]["evidence_id"]
            entry = {"quote": q, "match_ratio": round(ratio, 3), "start": s, "end": e, "source": c["source"]}
            summary["quotes"].append(entry)
            if 0.5 <= ratio < 0.75:
                entry["status"] = "partial"
                f = ctx.finding("text", c["evidence_id"] or ev_id, "context", "Quote only partially matches the recording",
                                f"The quote “{q[:160]}” matches the closest spoken passage at {ratio:.0%} (word level). "
                                "It may be paraphrased, truncated or altered.",
                                {"type": "text", "source": c["source"], "quote": q, "closest_segment": {"start": s, "end": e}},
                                0.45, 0.45, "quote_check",
                                limitations="ASR errors on names/numbers lower the match.",
                                alternatives=["Legitimate paraphrase", "Transcription error"])
                ctx.signal("quote_check", "text", c["evidence_id"] or ev_id, 0.45, 0.45, f"Quote match {ratio:.0%}.",
                           [f["id"]], label="Quote verification")
            elif ratio < 0.5:
                entry["status"] = "not found"
                f = ctx.finding("text", c["evidence_id"] or ev_id, "context",
                                "Quoted statement not found in the recording",
                                f"The claim attributes the quote “{q[:160]}” but the closest passage in the Whisper "
                                f"transcript matches only {ratio:.0%}. The media may not support what the caption says.",
                                {"type": "text", "source": c["source"], "quote": q,
                                 "closest_segment": {"start": s, "end": e}}, clamp(0.75 - ratio * 0.5), 0.55,
                                "quote_check", related=[],
                                limitations="Whisper can mis-transcribe names, accents and noisy speech; a paraphrased "
                                            "caption is not necessarily false.",
                                alternatives=["Paraphrase rather than exact quote", "Quote from a different part of a longer recording"])
                ctx.signal("quote_check", "text", c["evidence_id"] or ev_id, f["score"], 0.55,
                           f"Quote match {ratio:.0%}.", [f["id"]], label="Quote verification")
            else:
                entry["status"] = "found"
                ctx.signal("quote_check", "text", ev_id, 0.15, 0.5,
                           f"Quote found in transcript ({ratio:.0%}) at {fmt_ts(s or 0)}.", label="Quote verification")

    # ---------------- topical consistency -------------------------------------------
    tw = content(full_transcript)
    for c in claims:
        cw = content(c["text"])
        if len(cw) >= 6 and len(tw) >= 15:
            overlap = len(cw & tw) / len(cw)
            summary.setdefault("topic_overlap", []).append({"source": c["source"], "overlap": round(overlap, 3),
                                                            "shared_terms": sorted(cw & tw)[:20]})
            if overlap < 0.08:
                f = ctx.finding("text", c["evidence_id"], "context", "Caption topic not reflected in speech",
                                f"Only {overlap:.0%} of the caption's key terms occur in what is said in the media. "
                                "The caption may describe a different event than the recording.",
                                {"type": "text", "source": c["source"]}, 0.45, 0.3, "topic_overlap",
                                alternatives=["Caption describes visual content, not speech", "Different language"])
                ctx.signal("topic_overlap", "text", c["evidence_id"], 0.45, 0.3, f"Key-term overlap {overlap:.0%}.",
                           [f["id"]], label="Caption/speech topic overlap")
            else:
                ctx.signal("topic_overlap", "text", c["evidence_id"], 0.2, 0.3,
                           f"Key-term overlap {overlap:.0%}: caption consistent with speech.", label="Caption/speech topic overlap")

    # ---------------- dates & recency vs metadata ---------------------------------
    claim_text = " ".join(c["text"] for c in claims)
    cy = years_in(claim_text)
    try:
        created = dt.datetime.fromisoformat(case_created)
    except Exception:
        created = dt.datetime.now()
    for md in media_dates:
        try:
            when = dt.datetime.fromisoformat(str(md["when"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        entry = {"evidence_id": md["evidence_id"], "kind": md["kind"], "when": when.isoformat(), "claimed_years": sorted(cy)}
        summary["dates"].append(entry)
        if cy and when.year not in cy:
            f = ctx.finding("text", md["evidence_id"], "context", "Claimed date conflicts with media metadata",
                            f"The claim refers to {', '.join(map(str, sorted(cy)))}, but {md['evidence_id']}'s "
                            f"{md['kind']} is {when:%Y-%m-%d}. Recycled old media is a common form of misinformation.",
                            {"type": "metadata", "fields": [md["kind"]]}, 0.6, 0.4, "date_consistency",
                            limitations="Device clocks can be wrong and metadata is editable.",
                            alternatives=["Incorrect camera clock", "Caption refers to a later publication date"])
            ctx.signal("date_consistency", "text", md["evidence_id"], 0.6, 0.4, "Claimed year ≠ metadata year.",
                       [f["id"]], label="Date consistency")
        elif cy:
            ctx.signal("date_consistency", "text", md["evidence_id"], 0.2, 0.35, "Claimed year matches metadata.",
                       label="Date consistency")
        if any(re.search(p, claim_text, re.I) for p in RECENCY) and (created - when).days > 30:
            f = ctx.finding("text", md["evidence_id"], "context", "Presented as recent, but media is older",
                            f"The caption uses recency language (e.g. 'today', 'live') while metadata dates the media "
                            f"to {when:%Y-%m-%d}, {(created - when).days} days before this case was opened.",
                            {"type": "metadata", "fields": [md["kind"]]}, 0.55, 0.4, "date_consistency",
                            alternatives=["Metadata date reset by editing/export", "Caption reused from original post"])
            ctx.signal("date_consistency", "text", md["evidence_id"], 0.55, 0.4, "Recency claim vs old metadata.",
                       [f["id"]], label="Date consistency")

    # ---------------- supplied transcript vs audio ---------------------------------
    for st in supplied_transcripts:
        if not full_transcript.strip():
            ctx.limit(f"{st['id']}: supplied transcript could not be compared (no speech recognised in media).")
            continue
        a, b = words(st["clean"])[:1500], words(full_transcript)[:1500]
        ratio = SequenceMatcher(None, a, b, autojunk=False).ratio()
        summary["transcript_checks"].append({"evidence_id": st["id"], "similarity": round(ratio, 3)})
        if ratio < 0.5:
            f = ctx.finding("text", st["id"], "context", "Supplied transcript does not match the audio",
                            f"{st['filename']} agrees with the recognised speech only {ratio:.0%} (word sequence). "
                            "The transcript may be altered, or belong to a different recording.",
                            {"type": "text", "source": st["filename"]}, clamp(0.8 - ratio * 0.6), 0.5, "transcript_match",
                            alternatives=["Translation rather than verbatim transcript", "Poor ASR quality"])
            ctx.signal("transcript_match", "text", st["id"], f["score"], 0.5, f"Transcript similarity {ratio:.0%}.",
                       [f["id"]], label="Supplied transcript match")
        else:
            ctx.signal("transcript_match", "text", st["id"], 0.15, 0.5, f"Transcript similarity {ratio:.0%}.",
                       label="Supplied transcript match")

    # ---------------- sensational framing ------------------------------------------
    for c in claims:
        hits = [p for p in SENSATIONAL if re.search(p, c["text"], re.I)]
        caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", c["text"])]
        if len(hits) + (1 if len(caps) >= 3 else 0) + (1 if c["text"].count("!") >= 3 else 0) >= 2:
            f = ctx.finding("text", c["evidence_id"], "context", "Sensational / urgency framing",
                            "The accompanying text uses persuasion patterns common in misinformation (urgency, "
                            "'leaked', excessive capitals/exclamation). This says nothing about the media itself, "
                            "but warrants extra scrutiny of the claim.", {"type": "text", "source": c["source"]},
                            0.35, 0.2, "sensational_language", alternatives=["Ordinary social-media style"])
            ctx.signal("sensational_language", "text", c["evidence_id"], 0.35, 0.2, "Sensational framing.",
                       [f["id"]], label="Framing language")
    return summary
