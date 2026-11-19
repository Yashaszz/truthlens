"""Shared structures: findings (flagged, located indicators) and signals (every detector output, for fusion)."""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any

from .config import DETECTOR_IMPORTANCE


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return lo
    return max(lo, min(hi, float(x)))


def fmt_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"


class AnalysisContext:
    """Collects findings, signals and artifacts produced while analysing one case."""

    def __init__(self, case_dir: Path, case_id: str):
        self.case_dir = case_dir
        self.case_id = case_id
        self.artifact_dir = case_dir / "artifacts"
        self.work_dir = case_dir / "work"
        self.artifact_dir.mkdir(exist_ok=True)
        self.work_dir.mkdir(exist_ok=True)
        self.findings: list[dict] = []
        self.signals: list[dict] = []
        self.limitations: list[str] = []
        self.history: list[dict] = []
        self.per_evidence: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    # ---- ids -------------------------------------------------------------
    def _next(self, prefix: str) -> str:
        with self._lock:
            self._counters[prefix] = self._counters.get(prefix, 0) + 1
            return f"{prefix}-{self._counters[prefix]:03d}"

    def artifact_path(self, evidence_id: str, name: str) -> tuple[Path, str]:
        d = self.artifact_dir / evidence_id
        d.mkdir(parents=True, exist_ok=True)
        return d / name, f"artifacts/{evidence_id}/{name}"

    # ---- signals & findings ---------------------------------------------
    def signal(self, detector: str, modality: str, evidence_id: str | None, score: float,
               reliability: float, explanation: str, finding_ids: list[str] | None = None,
               label: str | None = None, extra: dict | None = None) -> dict:
        s = {
            "id": self._next("S"),
            "detector": detector,
            "label": label or detector.replace("_", " ").title(),
            "modality": modality,
            "evidence_id": evidence_id,
            "score": round(clamp(score), 4),
            "reliability": round(clamp(reliability), 3),
            "importance": DETECTOR_IMPORTANCE.get(detector, 0.5),
            "explanation": explanation,
            "finding_ids": finding_ids or [],
        }
        if extra:
            s["extra"] = extra
        self.signals.append(s)
        return s

    def finding(self, modality: str, evidence_id: str | None, category: str, title: str,
                description: str, location: dict, score: float, confidence: float,
                detector: str, artifacts: list[str] | None = None, limitations: str = "",
                alternatives: list[str] | None = None, related: list[str] | None = None) -> dict:
        f = {
            "id": self._next("F"),
            "modality": modality,
            "evidence_id": evidence_id,
            "category": category,
            "title": title,
            "description": description,
            "location": location,
            "score": round(clamp(score), 3),
            "confidence": round(clamp(confidence), 3),
            "detector": detector,
            "artifacts": artifacts or [],
            "limitations": limitations,
            "alternatives": alternatives or [],
            "related": related or [],
            "review": {"status": "pending", "note": "", "by": None, "at": None},
        }
        self.findings.append(f)
        return f

    def limit(self, text: str):
        if text not in self.limitations:
            self.limitations.append(text)

    def log(self, step: str, detail: str, **kw: Any):
        import datetime as _dt
        self.history.append({"at": _dt.datetime.now().isoformat(timespec="seconds"),
                             "step": step, "detail": detail, **kw})
