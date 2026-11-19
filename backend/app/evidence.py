"""Evidence intake: hashing, read-only original storage and chain-of-custody log."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

from .config import DATA_DIR

EXT_MODALITY = {
    **{e: "image" for e in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")},
    **{e: "video" for e in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")},
    **{e: "audio" for e in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".opus")},
    **{e: "text" for e in (".txt", ".md", ".srt", ".vtt", ".json")},
}


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def modality_for(filename: str) -> str | None:
    return EXT_MODALITY.get(Path(filename).suffix.lower())


def safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "file"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def case_dir(case_id: str) -> Path:
    if not re.fullmatch(r"TL-[0-9A-Za-z-]+", case_id):
        raise ValueError("invalid case id")
    return DATA_DIR / case_id


def custody(case_id: str, action: str, detail: str, **kw):
    entry = {"at": now(), "action": action, "detail": detail, **kw}
    with open(case_dir(case_id) / "custody.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_custody(case_id: str) -> list[dict]:
    p = case_dir(case_id) / "custody.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def new_case(title: str, context: str, examiner: str) -> dict:
    case_id = f"TL-{dt.datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
    d = DATA_DIR / case_id
    (d / "evidence").mkdir(parents=True)
    (d / "artifacts").mkdir()
    case = {
        "id": case_id,
        "title": title or "Untitled investigation",
        "examiner": examiner or "Unassigned",
        "context": context or "",
        "created_at": now(),
        "status": "created",
        "progress": {"stage": "ingest", "pct": 0, "message": "Case created"},
        "evidence": [],
        "results": None,
    }
    save_case(case)
    custody(case_id, "case_created", f"Case opened by {case['examiner']}")
    if context:
        custody(case_id, "context_recorded", "Investigator-supplied context / claims recorded",
                sha256=hashlib.sha256(context.encode()).hexdigest())
    return case


def ingest_file(case: dict, filename: str, fileobj) -> dict:
    modality = modality_for(filename)
    if modality is None:
        raise ValueError(f"Unsupported file type: {filename}")
    eid = f"E-{len(case['evidence']) + 1:03d}"
    stored = case_dir(case["id"]) / "evidence" / f"{eid}_{safe_name(filename)}"
    h = hashlib.sha256()
    size = 0
    with open(stored, "wb") as out:
        while chunk := fileobj.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
            out.write(chunk)
    os.chmod(stored, stat.S_IREAD)  # preserve original: read-only
    ev = {
        "id": eid,
        "filename": filename,
        "stored_as": f"evidence/{stored.name}",
        "modality": modality,
        "size": size,
        "sha256": h.hexdigest(),
        "received_at": now(),
    }
    case["evidence"].append(ev)
    custody(case["id"], "evidence_ingested", f"{filename} stored read-only as {eid}",
            evidence_id=eid, sha256=ev["sha256"], size=size)
    return ev


def verify_integrity(case: dict) -> list[dict]:
    out = []
    for ev in case["evidence"]:
        p = case_dir(case["id"]) / ev["stored_as"]
        ok = p.exists() and sha256_file(p) == ev["sha256"]
        out.append({"evidence_id": ev["id"], "sha256": ev["sha256"], "verified": ok})
        custody(case["id"], "integrity_check", f"{ev['id']} hash {'verified' if ok else 'MISMATCH'}",
                evidence_id=ev["id"], verified=ok)
    return out


def save_case(case: dict):
    p = DATA_DIR / case["id"] / "case.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(case, indent=2, default=str), encoding="utf-8")
    import time
    for attempt in range(10):  # Windows: the file may be briefly open by a concurrent reader
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, p)


def load_case(case_id: str) -> dict:
    return json.loads((case_dir(case_id) / "case.json").read_text(encoding="utf-8"))


def list_cases() -> list[dict]:
    out = []
    for d in sorted(DATA_DIR.glob("TL-*"), reverse=True):
        try:
            c = json.loads((d / "case.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        r = c.get("results") or {}
        out.append({
            "id": c["id"], "title": c["title"], "created_at": c["created_at"], "status": c["status"],
            "evidence_count": len(c["evidence"]),
            "modalities": sorted({e["modality"] for e in c["evidence"]}),
            "assessment": (r.get("fusion") or {}).get("overall", {}).get("band"),
        })
    return out
