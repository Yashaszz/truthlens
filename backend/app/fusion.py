"""Explainable evidence fusion.

Each detector output is a signal with score s (0 = no indication, 1 = strong indication of manipulation),
reliability r (how much this detector can be trusted under the observed conditions) and importance w.
Signals are pooled in log-odds space with weight w*r, plus a neutral prior weight that pulls the result
towards 0.5 ("unknown") when evidence is thin. The uncertainty band widens when signals disagree or
total evidence weight is low. Signals corroborated by cross-modal findings get a 1.3x weight.

Weights are expert priors documented in config.py: they are NOT empirically calibrated on a labelled
benchmark, and the report says so."""
from __future__ import annotations

import math

import numpy as np

from .common import clamp

PRIOR_WEIGHT = 1.0
BANDS = [
    ("strong", "Strong indicators of manipulation"),
    ("indicators", "Indicators of possible manipulation"),
    ("inconclusive", "Inconclusive: human review required"),
    ("none", "No significant manipulation indicators found"),
]


def _logit(p: float) -> float:
    p = clamp(p, 0.02, 0.98)
    return math.log(p / (1 - p))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def pool(signals: list[dict], corroborated: set[str]) -> dict:
    if not signals:
        return {"score": 0.5, "interval": [0.15, 0.85], "band": "inconclusive",
                "band_label": dict(BANDS)["inconclusive"], "agreement": None, "evidence_weight": 0.0,
                "drivers": [], "n_signals": 0}
    ws, ls, ss, contrib = [], [], [], []
    for s in signals:
        w = s["importance"] * s["reliability"]
        if set(s["finding_ids"]) & corroborated:
            w *= 1.3
        ws.append(w)
        ls.append(_logit(s["score"]))
        ss.append(s["score"])
    W = sum(ws)
    L = sum(w * l for w, l in zip(ws, ls)) / (W + PRIOR_WEIGHT)
    p = _sig(L)
    ss_a, ws_a = np.array(ss), np.array(ws)
    mean = float((ss_a * ws_a).sum() / W) if W else 0.5
    spread = float(math.sqrt(((ss_a - mean) ** 2 * ws_a).sum() / W)) if W else 0.5
    half = clamp(0.06 + 0.6 * spread + 0.3 / math.sqrt(1 + W), 0.06, 0.42)
    lo, hi = clamp(p - half), clamp(p + half)
    # a single high-reliability, high-score signal (e.g. generator metadata) must not be averaged away
    strong = [s for s in signals if s["reliability"] >= 0.7 and s["score"] >= 0.85]
    if strong:
        p = max(p, 0.8)
        lo = max(lo, 0.65)
        hi = max(hi, p)
    if lo >= 0.65:
        band = "strong"
    elif p >= 0.55:
        band = "indicators"
    elif hi <= 0.4:
        band = "none"
    else:
        band = "inconclusive"
    for s, w, l in zip(signals, ws, ls):
        contrib.append({"signal_id": s["id"], "label": s["label"], "modality": s["modality"],
                        "evidence_id": s["evidence_id"], "score": s["score"], "weight": round(w, 3),
                        "push": round(w * l / (W + PRIOR_WEIGHT), 4)})
    contrib.sort(key=lambda c: -abs(c["push"]))
    return {"score": round(p, 3), "interval": [round(lo, 3), round(hi, 3)], "band": band,
            "band_label": dict(BANDS)[band], "agreement": round(clamp(1 - 2 * spread), 3),
            "evidence_weight": round(W, 2), "drivers": contrib[:8], "n_signals": len(signals)}


def fuse(signals: list[dict], findings: list[dict]) -> dict:
    corroborated = set()
    for f in findings:
        if f["detector"] == "cross_modal":
            corroborated |= set(f["related"])
    modalities = sorted({s["modality"] for s in signals})
    evids = sorted({s["evidence_id"] for s in signals if s["evidence_id"]})
    return {
        "overall": pool(signals, corroborated),
        "by_modality": {m: pool([s for s in signals if s["modality"] == m], corroborated) for m in modalities},
        "by_evidence": {e: pool([s for s in signals if s["evidence_id"] == e], corroborated) for e in evids},
        "method": "Reliability-weighted log-odds pooling with neutral prior; uncertainty band from signal "
                  "disagreement and total evidence weight; 1.3x weight for cross-modally corroborated signals.",
    }
