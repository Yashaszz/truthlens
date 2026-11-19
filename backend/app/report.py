"""Forensic report: recommended human checks, global limitations and a self-contained HTML export."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .common import fmt_ts

GLOBAL_LIMITATIONS = [
    "Scores are indicators for human review, not proof of manipulation or authenticity.",
    "Detector reliability weights are expert priors; they have not been calibrated on a labelled benchmark for this deployment.",
    "Pretrained classifiers were trained on specific datasets/generators and may miss newer techniques or mis-fire on "
    "heavily compressed, filtered or out-of-distribution media.",
    "Absence of indicators does not establish authenticity; skilled manipulation can evade every automated check.",
]

RECS = {
    "synthetic-generation": "Ask the submitter for the original capture file/device; run a reverse image search for earlier copies.",
    "editing": "Obtain the camera-original file and compare; document every known processing step in the chain of custody.",
    "compositing": "Zoom into flagged regions: check lighting direction, shadows, edges and perspective against the rest of the scene.",
    "face-manipulation": "Step through flagged frames at full resolution: check face boundary, teeth, ears, eye reflections and glasses.",
    "temporal": "Review flagged timestamps frame-by-frame to determine whether cuts/freezes are editorial or conceal content.",
    "voice-synthesis": "Compare flagged audio segments against a verified reference recording of the claimed speaker (ideally with a phonetics expert).",
    "splicing": "Listen to the marked splice points on headphones at reduced speed; check for breaths, room-tone and clicks.",
    "av-sync": "Watch flagged segments at 0.5x with audio to judge lip-sync by eye; confirm the speaker is on-screen.",
    "context": "Verify the claim against the original publication/broadcast and independent sources.",
    "metadata": "Cross-check metadata with the device, platform of origin and the submitter's account.",
    "convergence": "Prioritise the converging time window: several independent channels flag it.",
}


def recommendations(findings: list[dict], links: list[dict], case: dict) -> list[dict]:
    out, seen = [], set()
    for f in sorted(findings, key=lambda f: -f["score"] * f["confidence"]):
        cat = f["category"]
        if cat in RECS and cat not in seen:
            seen.add(cat)
            out.append({"priority": "high" if f["score"] * f["confidence"] > 0.3 else "medium",
                        "check": RECS[cat], "because": f"{f['id']}: {f['title']}"})
    out.append({"priority": "standard", "check": "Confirm chain of custody and source of each file with the submitter.",
                "because": "Required for any evidential use."})
    if not any(e["modality"] in ("video", "audio") for e in case["evidence"]):
        out.append({"priority": "standard", "check": "If video/audio of the same event exists, add it to the case for cross-modal checks.",
                    "because": "Cross-modal correlation is stronger with multiple media types."})
    return out


def _loc_text(loc: dict) -> str:
    t = loc.get("type")
    if t == "regions":
        return "; ".join(f"{r.get('label', '')} @ x={r['bbox'][0]},y={r['bbox'][1]} {r['bbox'][2]}×{r['bbox'][3]}px"
                         for r in loc.get("regions", []))
    if t == "frames":
        return "Frames at " + ", ".join(fmt_ts(f["t"]) for f in loc.get("frames", [])[:10])
    if t == "segments":
        return "Segments " + ", ".join(f"{fmt_ts(s['start'])}–{fmt_ts(s['end'])}" for s in loc.get("segments", [])[:10])
    if t == "timestamps":
        return "At " + ", ".join(fmt_ts(x) for x in loc.get("times", [])[:10])
    if t == "metadata":
        return "Metadata: " + ", ".join(map(str, loc.get("fields", [])))
    if t == "text":
        return f"Text: {loc.get('source', '')}"
    return "Whole file"


def _img(case_dir: Path, rel: str) -> str:
    p = case_dir / rel
    if not p.exists() or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return ""
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f'<img src="data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}" alt="{html.escape(rel)}">'


def render_html(case: dict, case_dir: Path, custody: list[dict]) -> str:
    r = case["results"] or {}
    fu = r.get("fusion", {}).get("overall", {})
    e = html.escape
    band_color = {"strong": "#b42318", "indicators": "#c4320a", "inconclusive": "#8a6d00", "none": "#067647"}.get(fu.get("band"), "#555")
    ev_rows = "".join(
        f"<tr><td>{x['id']}</td><td>{e(x['filename'])}</td><td>{x['modality']}</td><td>{x['size']:,} B</td>"
        f"<td class=mono>{x['sha256']}</td><td>{'✔ verified' if any(i['evidence_id'] == x['id'] and i['verified'] for i in r.get('integrity', [])) else '✘'}</td></tr>"
        for x in case["evidence"])
    fnd = []
    for f in r.get("findings", []):
        imgs = "".join(_img(case_dir, a) for a in f.get("artifacts", [])[:2])
        rev = f.get("review", {})
        fnd.append(f"""<section class=finding>
<h3><span class=fid>{f['id']}</span> {e(f['title'])}</h3>
<div class=meta><b>Evidence</b> {f['evidence_id'] or '-'} · <b>Modality</b> {f['modality']} · <b>Category</b> {f['category']} ·
<b>Indicator score</b> {f['score']:.2f} · <b>Detector confidence</b> {f['confidence']:.2f} · <b>Detector</b> {f['detector']}</div>
<p><b>Flagged location:</b> {e(_loc_text(f['location']))}</p>
<p><b>Indicator:</b> {e(f['description'])}</p>
{f"<p><b>Limitations:</b> {e(f['limitations'])}</p>" if f.get('limitations') else ''}
{f"<p><b>Alternative explanations:</b> {e('; '.join(f['alternatives']))}</p>" if f.get('alternatives') else ''}
{f"<p><b>Related findings:</b> {', '.join(f['related'])}</p>" if f.get('related') else ''}
<p><b>Investigator review:</b> {e(rev.get('status', 'pending'))}{(' by ' + e(rev['by'])) if rev.get('by') else ''}{(' — ' + e(rev['note'])) if rev.get('note') else ''}</p>
<div class=imgs>{imgs}</div></section>""")
    links = "".join(f"<li><b>[{l['effect']}]</b> {e(l['title'])}: {e(l['description'])} <i>({', '.join(l['evidence_ids'])})</i></li>"
                    for l in r.get("links", [])) or "<li>No cross-modal relationships found.</li>"
    sig_rows = "".join(f"<tr><td>{s['label']}</td><td>{s['modality']}</td><td>{s['evidence_id'] or '-'}</td><td>{s['score']:.2f}</td>"
                       f"<td>{s['reliability']:.2f}</td><td>{e(s['explanation'])}</td></tr>" for s in r.get("signals", []))
    mods = "".join(f"<tr><td>{m}</td><td>{v['score']:.2f}</td><td>{v['interval'][0]:.2f}–{v['interval'][1]:.2f}</td><td>{e(v['band_label'])}</td></tr>"
                   for m, v in r.get("fusion", {}).get("by_modality", {}).items())
    drivers = "".join(f"<li>{e(d['label'])} ({d['evidence_id'] or '-'}): score {d['score']:.2f}, "
                      f"{'raises' if d['push'] > 0 else 'lowers'} suspicion</li>" for d in fu.get("drivers", [])[:6])
    recs = "".join(f"<li><b>{x['priority']}</b>: {e(x['check'])} <i>({e(x['because'])})</i></li>" for x in r.get("recommendations", []))
    lims = "".join(f"<li>{e(x)}</li>" for x in r.get("limitations", []))
    cust = "".join(f"<tr><td>{c['at']}</td><td>{c['action']}</td><td>{e(c['detail'])}</td></tr>" for c in custody)
    hist = "".join(f"<tr><td>{h['at']}</td><td>{h['step']}</td><td>{e(h['detail'])}</td></tr>" for h in r.get("history", []))
    eng = r.get("engine", {})
    return f"""<!doctype html><html><head><meta charset=utf-8><title>TruthLens Report {case['id']}</title>
<style>
body{{font:14px/1.5 system-ui,Segoe UI,sans-serif;color:#1d2433;max-width:1000px;margin:24px auto;padding:0 16px}}
h1{{margin:0}} h2{{border-bottom:2px solid #1d2433;padding-bottom:4px;margin-top:32px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}} td,th{{border:1px solid #d0d5dd;padding:5px 7px;text-align:left;vertical-align:top}}
th{{background:#f2f4f7}} .mono{{font-family:Consolas,monospace;font-size:11px;word-break:break-all}}
.verdict{{border-left:6px solid {band_color};background:#f9fafb;padding:12px 16px;margin:16px 0}}
.verdict .band{{font-size:20px;font-weight:700;color:{band_color}}}
.finding{{border:1px solid #d0d5dd;border-radius:6px;padding:10px 14px;margin:12px 0;page-break-inside:avoid}}
.finding h3{{margin:0 0 4px}} .fid{{background:#1d2433;color:#fff;border-radius:4px;padding:1px 6px;font-size:12px}}
.meta{{color:#475467;font-size:12.5px}} .imgs img{{max-width:48%;margin:4px;border:1px solid #d0d5dd}}
.notice{{background:#fffaeb;border:1px solid #fec84b;padding:10px 14px;border-radius:6px}}
</style></head><body>
<h1>TruthLens Forensic Report</h1>
<div class=meta>Case <b>{case['id']}</b> · {e(case['title'])} · Examiner: {e(case['examiner'])} · Opened {case['created_at']} · Report generated {r.get('generated_at', '')}</div>
<p class=notice><b>Interpretation:</b> Automated scores are investigative indicators, not verdicts. Every finding below lists its location,
the evidence that supports it, its limitations and alternative explanations, and must be reviewed by a qualified human examiner.</p>
<h2>1. Summary</h2>
<div class=verdict><div class=band>{e(fu.get('band_label', 'n/a'))}</div>
Fused indicator score <b>{fu.get('score', 0):.2f}</b> (uncertainty band {fu.get('interval', [0, 0])[0]:.2f}–{fu.get('interval', [0, 0])[1]:.2f}),
signal agreement {fu.get('agreement') if fu.get('agreement') is not None else 'n/a'}, {fu.get('n_signals', 0)} detector signals,
{len(r.get('findings', []))} flagged findings, {len(r.get('links', []))} cross-modal links.
{f"<br>Case assessment follows the most suspicious evidence item, <b>{fu['driven_by']}</b>; score pooled across all items: {fu.get('pooled_score', 0):.2f}." if fu.get('driven_by') else ''}</div>
<p><b>Main drivers:</b></p><ul>{drivers}</ul>
<table><tr><th>Modality</th><th>Score</th><th>Band</th><th>Assessment</th></tr>{mods}</table>
<h2>2. Case context</h2><p>{e(case.get('context') or 'No context supplied.')}</p>
<h2>3. Evidence &amp; source trace</h2>
<table><tr><th>ID</th><th>File</th><th>Type</th><th>Size</th><th>SHA-256</th><th>Integrity</th></tr>{ev_rows}</table>
<p class=meta>Originals are stored read-only; all analysis runs on derived copies. Hashes re-verified at report time.</p>
<h2>4. Flagged findings</h2>{''.join(fnd) or '<p>No findings exceeded flagging thresholds.</p>'}
<h2>5. Cross-modal context</h2><ul>{links}</ul>
<h2>6. All detector signals</h2>
<table><tr><th>Detector</th><th>Modality</th><th>Evidence</th><th>Score</th><th>Reliability</th><th>Observation</th></tr>{sig_rows}</table>
<p class=meta>Fusion method: {e(r.get('fusion', {}).get('method', ''))}</p>
<h2>7. Recommended human checks</h2><ol>{recs}</ol>
<h2>8. Limitations &amp; caveats</h2><ul>{lims}</ul>
<h2>9. Analysis history &amp; chain of custody</h2>
<p class=meta>Engine {eng.get('version', '')} on {e(str(eng.get('device', '')))}; models: {e(json.dumps(eng.get('models', {})))}; Whisper: {eng.get('whisper', '')}</p>
<table><tr><th>Time</th><th>Step</th><th>Detail</th></tr>{hist}</table><br>
<table><tr><th>Time</th><th>Custody action</th><th>Detail</th></tr>{cust}</table>
</body></html>"""
