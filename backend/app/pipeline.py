"""Orchestrates INGEST → ANALYZE → CORRELATE → (REVIEW) → REPORT for one case."""
from __future__ import annotations

import logging
import math
import time
import traceback

import numpy as np

from . import evidence as evs
from . import media, models
from .analyzers.audio import analyze_audio
from .analyzers.image import analyze_image
from .analyzers.sync import analyze_sync
from .analyzers.text import analyze_text
from .analyzers.video import analyze_video
from .common import AnalysisContext
from .config import APP_VERSION, MODELS, WHISPER_MODEL
from .correlate import correlate
from .fusion import fuse
from .report import recommendations, GLOBAL_LIMITATIONS

log = logging.getLogger("truthlens.pipeline")


def clean(o):
    """Make results JSON-safe: drop private (_*) keys and numpy objects, NaN -> None."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _progress(case: dict, stage: str, pct: int, msg: str):
    case["progress"] = {"stage": stage, "pct": pct, "message": msg}
    evs.save_case(case)


def run_analysis(case_id: str):
    case = evs.load_case(case_id)
    cdir = evs.case_dir(case_id)
    ctx = AnalysisContext(cdir, case_id)
    t0 = time.time()
    try:
        case["status"] = "running"
        evs.custody(case_id, "analysis_started", f"TruthLens {APP_VERSION} analysis started",
                    models=MODELS, whisper=WHISPER_MODEL, device=models.device_name())
        ctx.log("ingest", f"{len(case['evidence'])} evidence item(s) verified and queued")
        summaries: dict[str, dict] = {}
        transcripts, media_dates, text_ev = [], [], []
        media_items = [e for e in case["evidence"] if e["modality"] != "text"]
        for n, ev in enumerate(media_items):
            pct = 5 + int(70 * n / max(1, len(media_items)))
            path = cdir / ev["stored_as"]
            _progress(case, "analyze", pct, f"Analysing {ev['modality']} {ev['id']} ({ev['filename']})")
            t1 = time.time()
            try:
                if ev["modality"] == "image":
                    s = analyze_image(ctx, ev, path)
                    if s.get("capture_time"):
                        media_dates.append({"evidence_id": ev["id"], "kind": "EXIF capture time", "when": s["capture_time"]})
                elif ev["modality"] == "video":
                    s = analyze_video(ctx, ev, path)
                    prev = cdir / "artifacts" / ev["id"] / "preview.mp4"
                    prev.parent.mkdir(parents=True, exist_ok=True)
                    if media.to_browser_mp4(path, prev):
                        s["preview"] = f"artifacts/{ev['id']}/preview.mp4"
                    if s.get("has_audio"):
                        _progress(case, "analyze", pct + 5, f"Analysing audio track + transcript of {ev['id']}")
                        a = analyze_audio(ctx, ev, path, modality="audio", label="track")
                        s["audio"] = a
                        if a.get("transcript"):
                            transcripts.append({"evidence_id": ev["id"], "transcript": a["transcript"]})
                        _progress(case, "correlate", pct + 8, f"Audio-visual sync check for {ev['id']}")
                        sync = analyze_sync(ctx, ev, s, a)
                        if sync:
                            s["sync"] = sync
                    if s.get("creation_time"):
                        media_dates.append({"evidence_id": ev["id"], "kind": "container creation_time", "when": s["creation_time"]})
                elif ev["modality"] == "audio":
                    s = analyze_audio(ctx, ev, path)
                    prev = cdir / "artifacts" / ev["id"] / "preview.m4a"
                    prev.parent.mkdir(parents=True, exist_ok=True)
                    if media.to_browser_audio(path, prev):
                        s["preview"] = f"artifacts/{ev['id']}/preview.m4a"
                    if s.get("transcript"):
                        transcripts.append({"evidence_id": ev["id"], "transcript": s["transcript"]})
                else:
                    s = {}
                summaries[ev["id"]] = s
                ctx.log("analyze", f"{ev['id']} {ev['modality']} analysed in {time.time() - t1:.1f}s",
                        evidence_id=ev["id"])
            except Exception as e:
                log.exception("analysis of %s failed", ev["id"])
                ctx.limit(f"{ev['id']}: analysis failed ({type(e).__name__}: {e}).")
                summaries[ev["id"]] = {"error": str(e)}
                ctx.log("analyze", f"{ev['id']} FAILED: {e}", evidence_id=ev["id"])

        for ev in case["evidence"]:
            if ev["modality"] == "text":
                try:
                    body = (cdir / ev["stored_as"]).read_text(encoding="utf-8", errors="replace")[:200_000]
                except Exception:
                    body = ""
                text_ev.append({"id": ev["id"], "filename": ev["filename"], "content": body})
                summaries[ev["id"]] = {"chars": len(body), "preview": body[:2000]}

        _progress(case, "analyze", 78, "Text & context analysis")
        tsum = analyze_text(ctx, case.get("context", ""), text_ev, transcripts, media_dates, case["created_at"])
        ctx.log("analyze", f"text/context: {len(tsum['quotes'])} quote(s), {len(tsum['dates'])} date check(s)")

        _progress(case, "correlate", 85, "Correlating signals across modalities")
        links = correlate(ctx, case["evidence"], summaries)
        ctx.log("correlate", f"{len(links)} cross-modal link(s) established")

        _progress(case, "report", 93, "Fusing evidence and building report")
        fusion = fuse(ctx.signals, ctx.findings)
        integrity = evs.verify_integrity(case)
        ctx.findings.sort(key=lambda f: -(f["score"] * (0.5 + f["confidence"])))
        case["results"] = clean({
            "generated_at": evs.now(),
            "duration_s": round(time.time() - t0, 1),
            "engine": {"version": APP_VERSION, "models": MODELS, "whisper": WHISPER_MODEL,
                       "device": models.device_name(), "model_status": models.status()},
            "fusion": fusion,
            "findings": ctx.findings,
            "signals": ctx.signals,
            "links": links,
            "evidence_summaries": summaries,
            "text_analysis": tsum,
            "limitations": GLOBAL_LIMITATIONS + ctx.limitations,
            "recommendations": recommendations(ctx.findings, links, case),
            "integrity": integrity,
            "history": ctx.history,
        })
        case["status"] = "complete"
        case["progress"] = {"stage": "review", "pct": 100, "message": "Analysis complete: ready for review"}
        evs.save_case(case)
        evs.custody(case_id, "analysis_completed",
                    f"{len(ctx.findings)} findings, assessment: {fusion['overall']['band_label']}",
                    score=fusion["overall"]["score"], interval=fusion["overall"]["interval"])
    except Exception as e:  # pragma: no cover
        log.exception("case %s failed", case_id)
        case["status"] = "failed"
        case["progress"] = {"stage": "error", "pct": 100, "message": f"{type(e).__name__}: {e}"}
        case["error"] = traceback.format_exc()[-3000:]
        evs.save_case(case)
        evs.custody(case_id, "analysis_failed", str(e))
