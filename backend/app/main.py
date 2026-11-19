"""TruthLens API."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import evidence as evs
from . import models
from .config import APP_VERSION, MODES, resolve_options
from .pipeline import run_analysis
from .plain import summarize
from .report import render_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warm all models in the background: the server accepts requests immediately, and the first upload no
    # longer pays the 15-30 s model-load cost. Disable with TRUTHLENS_PRELOAD=0.
    if os.getenv("TRUTHLENS_PRELOAD", "1") == "1":
        threading.Thread(target=models.preload, name="model-warmup", daemon=True).start()
    yield


app = FastAPI(title="TruthLens", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
@app.middleware("http")
async def no_stale_shell(request, call_next):
    # index.html must always be revalidated so a rebuilt UI (new hashed assets) is picked up immediately
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


_jobs: dict[str, threading.Thread] = {}
_case_locks: dict[str, threading.Lock] = {}


def _load(case_id: str) -> dict:
    try:
        return evs.load_case(case_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "case not found")


@app.get("/api/health")
def health():
    from . import online
    return {"status": "ok", "version": APP_VERSION, "modes": MODES,
            "web_search": online.provider(), "web_search_missing": online.missing_keys(),
            "samples_ready": (SAMPLES / "tts_speech.wav").exists(), **models.status()}


@app.get("/api/accuracy")
def accuracy():
    """Measured accuracy of the shipped detectors (written by the backend/eval benchmark scripts)."""
    from .detectors import load_calib
    from . import analyzers
    out = {}
    ai = load_calib("ai_image")
    if ai:
        out["ai_image"] = {"name": "AI-generated images", "models": ai["models"], "heldout": ai["lodo"], "per_set": ai["lodo_per_set"],
                           "baseline": ai.get("single_best_lodo"), "protocol": "Leave-one-dataset-out over GenImage, CommunityForensics-Eval, WebArt"}
    fh = load_calib("face_head")
    if fh:
        out["face_swap"] = {"name": "Face swaps & synthetic faces", "models": [fh["backbone"] + " + trained head"], "heldout": fh["test"],
                            "baseline": fh.get("baseline_test"), "per_group": fh.get("per_group"),
                            "protocol": "Trained on DeepFakeFace train split, tested on its separate test split"}
    vo = load_calib("voice")
    if vo:
        out["voice"] = {"name": "Cloned / synthetic voices", "models": vo["models"], "heldout": vo["cross_dataset"], "per_set": vo["per_set"],
                        "protocol": "Cross-dataset: calibrated on one of In-the-Wild / ElevenLabs set, tested on the other"}
    mp = load_calib("manipulation")
    if mp:
        out["manipulation_classical"] = {"name": "Classical forensics (ELA, noise, JPEG, copy-move)", "heldout": mp["cv"],
                                         "per_set": mp.get("by_dataset"), "protocol": "5-fold CV on CASIA/IMD2020/OpenSDID/TGIF tampering benchmarks"}
    from pathlib import Path as _P
    res = _P(__file__).resolve().parents[1] / "eval" / "results"
    for key, fname in (("hidden_ai", "hidden_ai_summary.json"), ("trufor", "trufor_summary.json")):
        f = res / fname
        if f.exists():
            out[key] = json.loads(f.read_text())
    from .analyzers import trufor as _tf
    out["trufor_installed"] = _tf.available()
    return out


@app.get("/api/cases")
def cases():
    return evs.list_cases()


def _start(case_id: str):
    t = threading.Thread(target=run_analysis, args=(case_id,), daemon=True)
    _jobs[case_id] = t
    t.start()


def _parse_options(raw: str) -> dict:
    try:
        return resolve_options(json.loads(raw) if raw else None)
    except (ValueError, TypeError):
        raise HTTPException(400, "options must be JSON")


@app.post("/api/cases")
async def create_case(files: list[UploadFile] = File(...), context: str = Form(""), title: str = Form(""),
                      examiner: str = Form(""), options: str = Form("")):
    def _kind(f):
        head = f.file.read(16)
        f.file.seek(0)
        return evs.modality_for(f.filename or "", head)
    bad = [f.filename for f in files if not _kind(f)]
    if bad:
        raise HTTPException(400, f"Unsupported file type(s): {', '.join(bad)}")
    opts = _parse_options(options)
    case = evs.new_case(title, context, examiner)
    case["options"] = opts
    for f in files:
        evs.ingest_file(case, f.filename, f.file)
    case["status"] = "queued"
    case["progress"] = {"stage": "ingest", "pct": 3, "message": f"{len(files)} file(s) ingested and hashed"}
    evs.save_case(case)
    _start(case["id"])
    return {"id": case["id"]}


SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@app.post("/api/demo")
def demo_case():
    """One-click sample case: a tampered photo, a spliced synthetic-voice recording, a 'dubbed' video and a
    misleading caption. Builds the sample files on first use."""
    need = ["photo_tampered.jpg", "tts_spliced.wav", "dubbed_clip.mp4", "caption.txt"]
    if not all((SAMPLES / n).exists() for n in need):
        script = Path(__file__).resolve().parents[1] / "scripts" / "make_samples.py"
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise HTTPException(500, f"Could not build samples: {r.stderr[-400:]}")
    case = evs.new_case("Sample case: viral 'mayor' clip", (SAMPLES / "caption.txt").read_text(encoding="utf-8"), "Demo")
    case["options"] = resolve_options(None)
    for n in need[:3]:
        with open(SAMPLES / n, "rb") as fh:
            evs.ingest_file(case, n, fh)
    case["status"] = "queued"
    case["progress"] = {"stage": "ingest", "pct": 3, "message": "Sample files ingested and hashed"}
    evs.save_case(case)
    _start(case["id"])
    return {"id": case["id"]}


class Rerun(BaseModel):
    mode: str = "standard"
    models: bool = True
    transcribe: bool = True
    lipsync: bool = True


@app.post("/api/cases/{case_id}/rerun")
def rerun_case(case_id: str, body: Rerun):
    lock = _case_locks.setdefault(case_id, threading.Lock())
    with lock:
        c = _load(case_id)
        if c["status"] in ("queued", "running"):
            raise HTTPException(409, "analysis already running")
        reviewed = sum(1 for f in (c.get("results") or {}).get("findings", []) if f["review"]["status"] != "pending")
        c["options"] = resolve_options(body.model_dump())
        c["status"] = "queued"
        c["results"] = None
        c["progress"] = {"stage": "ingest", "pct": 3, "message": "Re-checking with new settings"}
        evs.save_case(c)
    evs.custody(case_id, "reanalysis_requested", f"Re-analysis in {c['options']['mode']} mode"
                + (f"; {reviewed} earlier examiner decision(s) remain in this log" if reviewed else ""), options=c["options"])
    _start(case_id)
    return {"id": case_id}


class CasePatch(BaseModel):
    title: str | None = None
    notes: str | None = None


@app.patch("/api/cases/{case_id}")
def patch_case(case_id: str, body: CasePatch):
    lock = _case_locks.setdefault(case_id, threading.Lock())
    with lock:
        c = _load(case_id)
        changes = []
        if body.title is not None and body.title.strip() and body.title != c["title"]:
            changes.append(f"renamed from '{c['title']}' to '{body.title.strip()[:120]}'")
            c["title"] = body.title.strip()[:120]
        if body.notes is not None and body.notes != c.get("notes", ""):
            c["notes"] = body.notes[:10000]
            c["notes_updated"] = evs.now()
            changes.append("examiner notes updated")
        if changes:
            evs.save_case(c)
    for ch in changes:
        evs.custody(case_id, "case_updated", ch)
    return {"title": c["title"], "notes": c.get("notes", ""), "notes_updated": c.get("notes_updated")}


@app.post("/api/cases/{case_id}/online")
def search_online(case_id: str):
    """Look for exact copies of the case's images / video keyframes on the public web."""
    from . import online
    if online.provider() is None:
        raise HTTPException(400, "Web search is not configured: add SERPAPI_KEY + IMGBB_KEY (or GOOGLE_VISION_KEY) to backend/.env "
                                 "and restart the server.")
    c = _load(case_id)
    items = {}
    sent = 0
    for ev in c["evidence"]:
        if ev["modality"] not in ("image", "video"):
            continue
        frames = online.frames_for(evs.case_dir(case_id) / ev["stored_as"], ev["modality"])
        sent += len(frames)
        items[ev["id"]] = online.search_frames(frames)
    result = {"at": evs.now(), "provider": online.provider(), "items": items,
              "total_matches": sum(len(r.get("matches", [])) for r in items.values()),
              "fact_checks": sum(r.get("fact_checks", 0) for r in items.values())}
    lock = _case_locks.setdefault(case_id, threading.Lock())
    with lock:
        c = _load(case_id)
        c["online"] = result
        evs.save_case(c)
    evs.custody(case_id, "web_search", f"{sent} image(s)/keyframe(s) sent to {result['provider']} for exact-match search; "
                                       f"{result['total_matches']} verified match(es)", provider=result["provider"])
    return result


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str):
    c = _load(case_id)
    if c["status"] in ("queued", "running"):
        raise HTTPException(409, "wait for the analysis to finish before deleting")
    evs.delete_case(case_id)
    return {"deleted": case_id}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    c = _load(case_id)
    c["custody"] = evs.read_custody(case_id)
    c["summary"] = summarize(c)
    return JSONResponse(c)


class Review(BaseModel):
    status: str  # confirmed | dismissed | needs-follow-up | pending
    note: str = ""
    by: str = ""


@app.patch("/api/cases/{case_id}/findings/{finding_id}")
def review_finding(case_id: str, finding_id: str, body: Review):
    if body.status not in ("confirmed", "dismissed", "needs-follow-up", "pending"):
        raise HTTPException(400, "invalid status")
    lock = _case_locks.setdefault(case_id, threading.Lock())
    with lock:
        c = _load(case_id)
        if c.get("status") != "complete":
            raise HTTPException(409, "analysis not complete")
        f = next((x for x in c["results"]["findings"] if x["id"] == finding_id), None)
        if not f:
            raise HTTPException(404, "finding not found")
        f["review"] = {"status": body.status, "note": body.note[:2000], "by": body.by or c["examiner"], "at": evs.now()}
        evs.save_case(c)
    evs.custody(case_id, "finding_reviewed", f"{finding_id} marked {body.status}" + (f": {body.note[:200]}" if body.note else ""),
                finding_id=finding_id, by=f["review"]["by"])
    return f["review"]


@app.get("/api/cases/{case_id}/report.html", response_class=HTMLResponse)
def report_html(case_id: str, download: bool = False):
    c = _load(case_id)
    if not c.get("results"):
        raise HTTPException(409, "analysis not complete")
    evs.custody(case_id, "report_exported", "HTML forensic report generated")
    html = render_html(c, evs.case_dir(case_id), evs.read_custody(case_id))
    headers = {"Content-Disposition": f'attachment; filename="{case_id}_report.html"'} if download else {}
    return HTMLResponse(html, headers=headers)


@app.get("/api/cases/{case_id}/report.json")
def report_json(case_id: str):
    c = _load(case_id)
    c["custody"] = evs.read_custody(case_id)
    c["summary"] = summarize(c)
    evs.custody(case_id, "report_exported", "JSON forensic report exported")
    return JSONResponse(c, headers={"Content-Disposition": f'attachment; filename="{case_id}_report.json"'})


@app.get("/api/cases/{case_id}/files/{rel:path}")
def case_file(case_id: str, rel: str):
    base = evs.case_dir(case_id).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file() or not (rel.startswith("artifacts/") or rel.startswith("evidence/")):
        raise HTTPException(404, "file not found")
    return FileResponse(p)


# Serve the built frontend (npm run build) if present, so one process can run the whole demo.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
