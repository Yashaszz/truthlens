from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve


def summarize(y: np.ndarray, p: np.ndarray) -> dict:
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    out = {"n": int(len(y)), "acc@0.5": float(((p >= 0.5) == y).mean()) if len(y) else None}
    if len(set(y)) == 2:
        out["auc"] = float(roc_auc_score(y, p))
        fpr, tpr, thr = roc_curve(y, p)
        fnr = 1 - tpr
        i = int(np.nanargmin(np.abs(fnr - fpr)))
        out["eer"] = float((fpr[i] + fnr[i]) / 2)
        accs = [((p >= t) == y).mean() for t in thr[1:]]
        j = int(np.argmax(accs))
        out["best_acc"] = float(accs[j])
        out["best_thr"] = float(thr[1:][j])
        out["tpr@0.5"] = float((p[y == 1] >= 0.5).mean())
        out["tnr@0.5"] = float((p[y == 0] < 0.5).mean())
    return out


def ece(y, p, bins: int = 10) -> float:
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & (p < b if b < 1 else p <= b)
        if m.any():
            e += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(e)
