"""TruthLens API."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import evidence as evs
from . import models
from .config import APP_VERSION
from .pipeline import run_analysis
from .report import render_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="TruthLens", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
_jobs: dict[str, threading.Thread] = {}
_case_locks: dict[str, threading.Lock] = {}


def _load(case_id: str) -> dict:
    try:
        return evs.load_case(case_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "case not found")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION, **models.status()}


@app.get("/api/cases")
def cases():
    return evs.list_cases()


@app.post("/api/cases")
async def create_case(files: list[UploadFile] = File(...), context: str = Form(""), title: str = Form(""),
                      examiner: str = Form("")):
    bad = [f.filename for f in files if not evs.modality_for(f.filename or "")]
    if bad:
        raise HTTPException(400, f"Unsupported file type(s): {', '.join(bad)}")
    case = evs.new_case(title, context, examiner)
    for f in files:
        evs.ingest_file(case, f.filename, f.file)
    case["status"] = "queued"
    case["progress"] = {"stage": "ingest", "pct": 3, "message": f"{len(files)} file(s) ingested and hashed"}
    evs.save_case(case)
    t = threading.Thread(target=run_analysis, args=(case["id"],), daemon=True)
    _jobs[case["id"]] = t
    t.start()
    return {"id": case["id"]}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    c = _load(case_id)
    c["custody"] = evs.read_custody(case_id)
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
