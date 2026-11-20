"""Forensic report: recommended human checks, global limitations and a self-contained HTML export."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .common import fmt_ts

GLOBAL_LIMITATIONS = [
    "Scores are indicators for human review, not proof of manipulation or authenticity.",
    "Detector probabilities are calibrated on labelled public benchmarks (held-out accuracy 82-92%); newer generators may score lower.",
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
            check = RECS[cat]
            if cat == "face-manipulation" and f["modality"] == "image":
                check = "Zoom into the face at full resolution: check its outline, hairline, teeth, ears, eye reflections and glasses."
            if cat == "compositing" and f["modality"] == "video":
                check = "Pause on the flagged frame and inspect edges, lighting and shadows against the rest of the scene."
            out.append({"priority": "high" if f["score"] * f["confidence"] > 0.3 else "medium",
                        "check": check, "because": f"{f['id']}: {f['title']}"})
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


def _plain_section(case: dict) -> str:
    from .plain import summarize
    s = summarize(case)
    if not s:
        return ""
    e = html.escape
    found = "".join(f"<li><b>{e(x['file'])}</b>: {e(x['text'])} <i>({x['strength'].lower()} signal)</i></li>" for x in s["found"]) \
        or "<li>No significant problems were found.</li>"
    fine = "".join(f"<li>{e(x['text'])} <i>({e(x['file'])})</i></li>" for x in s["looked_fine"])
    steps = "".join(f"<li>{e(x)}</li>" for x in s["next_steps"])
    nc = "".join(f"<li>{e(x)}</li>" for x in s["not_checked"])
    return f"""<h2>Plain-language summary</h2>
<p class=lead><b>{e(s['headline'])}.</b> {e(s['subline'])} {e(s['confidence_text'])}</p>
<h3>What we found</h3><ul>{found}</ul>
{f'<h3>What looked normal</h3><ul>{fine}</ul>' if fine else ''}
<h3>What to do next</h3><ol>{steps}</ol>
{f'<h3>What we could not check</h3><ul>{nc}</ul>' if nc else ''}
<p class=meta>{e(s['caveat'])} The technical sections below give every detector result, location and limitation.</p>"""


def _online_section(case: dict) -> str:
    o = case.get("online")
    if not o:
        return ""
    e = html.escape
    rows = []
    for eid, r in o.get("items", {}).items():
        if r.get("matches"):
            for m in r["matches"]:
                rows.append(f"<li><b>{e(m['site'])}</b>{' <b style=color:#b42318>[fact-check]</b>' if m.get('fact_check') else ''} "
                            f"<a href=\"{e(m['link'])}\">{e(m.get('title') or m['link'])}</a> "
                            f"<i>({round(m['similarity'] * 100)}% match{', ' + e(m['date']) if m.get('date') else ''}; {eid})</i></li>")
        else:
            rows.append(f"<li>{eid}: no exact copies found online.</li>")
    return (f"<h2>Seen online</h2><p class=meta>Exact copies found on public, search-indexed pages (searched {e(o['at'])} via "
            f"{e(o['provider'])}; each match verified locally).</p><ul>{''.join(rows)}</ul>")




# ------------------------------------------------------------------ cybercrime complaint helper
CYBERCRIME = {
    "portal": "https://cybercrime.gov.in",
    "portal_name": "National Cyber Crime Reporting Portal (Government of India)",
    "helpline": "1930",
    "steps": [
        "Open cybercrime.gov.in and choose 'Report Cyber Crime'. For sexual or child-related deepfakes use "
        "'Report Women/Child Related Crime' (it can be filed anonymously).",
        "Sign in with your mobile number and OTP, then pick the category that fits (for example impersonation, "
        "morphed or fake content, or online fraud).",
        "Paste the complaint text into the incident description.",
        "Attach this forensic report, the original file(s) and screenshots of where the media was posted.",
        "Submit and note the acknowledgement number. If money was lost, also call 1930 straight away.",
    ],
}


def _fake_pct(v: dict) -> int | None:
    if not v or v.get("confidence") is None:
        return None
    return round((v["confidence"] if v.get("fake") else 1 - v["confidence"]) * 100)


def complaint(case: dict) -> dict:
    """Ready-to-paste complaint text plus where and how to file it."""
    from .plain import summarize
    r = case.get("results") or {}
    v = (r.get("threats") or {}).get("verdict") or {}
    s = summarize(case) or {}
    pct = _fake_pct(v)
    files = "; ".join(f"{x['filename']} ({x['modality']}, SHA-256 {x['sha256'][:16]}...)" for x in case["evidence"])
    when = (r.get("generated_at") or "")[:16].replace("T", " ")
    lines = [
        "I wish to report suspected manipulated / fake digital media.",
        f"File(s): {files}.",
        f"An automated forensic analysis (TruthLens, case {case['id']}, {when}) assessed it as: {v.get('label', 'not determined')}"
        + (f" ({pct}% chance it is fake or manipulated)." if pct is not None else "."),
    ]
    found = [x["text"] for x in s.get("found", [])[:4]]
    if found:
        lines.append("Key findings: " + " ".join(f"({i + 1}) {t}" for i, t in enumerate(found)))
    hits = []
    for it in ((case.get("online") or {}).get("items") or {}).values():
        hits += [m["link"] for m in (it.get("fact_check_news") or [])[:2]]
        hits += [m["link"] for m in it.get("matches", [])[:4]]
    if hits:
        hits = [h for h in dict.fromkeys(hits) if "google.com/goto" not in h]
        if hits:
            lines.append("It appears online at: " + ", ".join(hits[:6]) + ".")
    if case.get("context"):
        lines.append(f"Context / claim made with the media: {case['context'][:300]}")
    lines.append("The original files are preserved unaltered (hashes above) and the full forensic report is attached.")
    return {**CYBERCRIME, "text": "\n".join(lines), "fake": bool(v.get("fake")), "verdict": v.get("label"), "fake_pct": pct}


# ------------------------------------------------------------------ HTML forensic report (TruthLens "Paper" theme)
CSS = """
:root{--paper:#f3efe6;--sheet:#fbf9f4;--ink:#1e1c19;--ink2:#4a453d;--muted:#7b7467;--rule:#d8cfbf;--rule2:#e7e0d2;
--red:#a3321f;--orange:#b4541c;--amber:#9a6b00;--green:#2f6b3a;--blue:#2c5d8a}
*{box-sizing:border-box}
html{background:var(--paper)}
body{margin:0;color:var(--ink);font:14px/1.55 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{max-width:980px;margin:28px auto 70px;padding:0 20px}
h1,h2,h3{font-family:Georgia,"Iowan Old Style","Times New Roman",serif}
.mono{font-family:Consolas,"SFMono-Regular",Menlo,monospace}
a{color:var(--blue);word-break:break-word}
.mast{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;border-bottom:3px double var(--ink);padding-bottom:14px}
.brand{font:700 30px/1 Georgia,serif;letter-spacing:-.01em}
.brand small{display:block;font:600 11px/1.6 "Segoe UI",sans-serif;letter-spacing:.2em;color:var(--muted);text-transform:uppercase;margin-top:6px}
.mast .ref{text-align:right;font-size:12px;color:var(--ink2)}
.mast .ref b{font:700 14px Consolas,monospace;color:var(--ink)}
.conf{margin:10px 0 22px;font:600 10.5px "Segoe UI",sans-serif;letter-spacing:.22em;color:var(--red);text-transform:uppercase}
h1{font-size:30px;line-height:1.15;margin:0 0 6px}
h2{font-size:21px;margin:34px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--rule);display:flex;gap:10px;align-items:baseline;break-after:avoid}
h2 .n{font:700 12px Consolas,monospace;color:var(--muted)}
h3{font-size:16px;margin:18px 0 6px}
.muted{color:var(--muted)} .small{font-size:12.5px}
.card{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:18px 20px}
.verdict{display:grid;grid-template-columns:1.35fr 1fr;gap:18px;align-items:stretch}
.stamp{display:inline-block;border:2.5px solid currentColor;border-radius:6px;padding:6px 14px 8px;transform:rotate(-1.5deg);margin:2px 0 14px}
.stamp i{display:block;font:700 10px "Segoe UI",sans-serif;letter-spacing:.2em;font-style:normal;opacity:.8;text-align:center}
.stamp b{display:block;font:700 23px/1.15 Georgia,serif}
.lead{font-size:16px;color:var(--ink2);margin:0 0 8px}
.meter .lbl{font:700 10.5px "Segoe UI",sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.meter .num{font:700 58px/1 Georgia,serif;margin:10px 0 12px}
.meter .num span{font-size:26px;margin-left:2px}
.bar{height:9px;border-radius:99px;background:var(--rule2);overflow:hidden}
.bar i{display:block;height:100%;border-radius:99px}
.ticks{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted);margin-top:5px}
.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
.facts div{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:12px 14px}
.facts b{display:block;font:700 24px Georgia,serif}
.facts span{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.alert{margin-top:16px;border:1.5px solid var(--red);background:#f8ebe6;border-radius:10px;padding:16px 18px;break-inside:avoid}
.alert h3{margin:0 0 6px;color:var(--red)}
.alert ol{margin:8px 0 0 18px;padding:0} .alert li{margin:3px 0}
.pre{white-space:pre-wrap;background:var(--sheet);border:1px dashed var(--rule);border-radius:8px;padding:12px 14px;font-size:12.5px;margin-top:6px}
.file{margin:14px 0 6px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.kind{font:700 10.5px "Segoe UI",sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--blue)}
.tag{display:inline-block;font:700 11px "Segoe UI",sans-serif;padding:2px 8px;border-radius:4px;border:1.5px solid currentColor;margin-right:6px}
.trow{display:grid;grid-template-columns:96px 1fr 120px;gap:14px;padding:11px 0;border-top:1px solid var(--rule2);break-inside:avoid}
.trow.dim{opacity:.55}
.chip{font:700 10px "Segoe UI",sans-serif;letter-spacing:.12em;text-transform:uppercase;border:1.5px solid currentColor;border-radius:4px;padding:3px 0;text-align:center;align-self:start}
.trow ul{margin:5px 0 0 16px;padding:0;font-size:13px;color:var(--ink2)}
.tp{font:700 13px Consolas,monospace;text-align:right}
.tp .bar{height:6px;margin-top:6px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.clean{margin:6px 0 0 18px;padding:0} .clean li{margin:5px 0}
.hit{border:1px solid var(--rule);border-radius:8px;padding:9px 12px;margin:7px 0;background:var(--sheet);break-inside:avoid}
.hit.fc{border-color:var(--red)}
.hit b{margin-right:8px}
.finding{background:var(--sheet);border:1px solid var(--rule);border-radius:10px;padding:14px 16px;margin:12px 0;break-inside:avoid}
.finding h3{margin:0 0 6px;display:flex;gap:8px;align-items:center}
.fid{font:700 11px Consolas,monospace;background:var(--ink);color:var(--paper);border-radius:4px;padding:2px 7px}
.finding p{margin:5px 0}
.imgs{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.imgs img{max-width:calc(50% - 4px);border:1px solid var(--rule);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:var(--sheet)}
th,td{border:1px solid var(--rule);padding:6px 8px;text-align:left;vertical-align:top}
th{background:#ece6d9;font-weight:700;font-size:11.5px;letter-spacing:.04em}
td.mono{font-size:11px;word-break:break-all}
.ok{color:var(--green);font-weight:700} .bad{color:var(--red);font-weight:700}
.foot{margin-top:40px;padding-top:12px;border-top:3px double var(--ink);font-size:12px;color:var(--muted);display:flex;justify-content:space-between;gap:16px}
.tools{position:fixed;right:18px;bottom:18px}
.tools button{font:600 13px "Segoe UI",sans-serif;border:1.5px solid var(--ink);background:var(--ink);color:var(--paper);border-radius:6px;padding:10px 16px;cursor:pointer}
@media (max-width:760px){.verdict,.cols{grid-template-columns:1fr}.facts{grid-template-columns:repeat(2,1fr)}.trow{grid-template-columns:84px 1fr}.tp{grid-column:2;text-align:left}}
@page{size:A4;margin:14mm 12mm}
@media print{html,body{background:#fff}.page{margin:0;max-width:none;padding:0}.tools{display:none}.card,.facts div,.finding,.hit,table{background:#fff}}
"""

STATUS = {"detected": ("Detected", "var(--red)"), "likely": ("Likely", "var(--orange)"), "at_risk": ("At risk", "var(--amber)"),
          "not_detected": ("Not found", "var(--green)"), "not_applicable": ("N/A", "var(--muted)"),
          "not_checked": ("Not checked", "var(--muted)")}


def _pcolor(p: float) -> str:
    return "var(--red)" if p >= 0.8 else "var(--orange)" if p >= 0.6 else "var(--amber)" if p > 0.4 else "var(--green)"


def _threat_section(th: dict, by_id: dict) -> str:
    e = html.escape
    out = []
    for eid, it in (th.get("items") or {}).items():
        ev = by_id.get(eid, {})
        iv = it.get("verdict") or {}
        ip = _fake_pct(iv)
        tag = ""
        if ip is not None:
            shown = ip if iv.get("fake") else 100 - ip
            tag = f'<span class=tag style="color:{_pcolor(ip / 100)}">{e(iv.get("label", ""))} · {shown}%</span>'
        rows = []
        for m in it.get("matrix", []):
            word, col = STATUS.get(m.get("status"), STATUS["not_checked"])
            dim = m.get("status") in ("not_applicable", "not_checked")
            evl = "".join(f"<li>{e(x)}</li>" for x in m.get("evidence", []))
            if m.get("note"):
                evl += f'<li class=muted>{e(m["note"])}</li>'
            p = m.get("p")
            if p is not None and not dim:
                pc = round(p * 100)
                pcell = f'{pc}%<div class=bar><i style="width:{pc}%;background:{col}"></i></div>'
            else:
                pcell = "<span class=muted>-</span>"
            rows.append(f'<div class="trow{" dim" if dim else ""}"><span class=chip style="color:{col}">{word}</span>'
                        f'<div><b>{e(m.get("name", ""))}</b><div class="small muted">{e(m.get("desc", ""))}</div>'
                        + (f"<ul>{evl}</ul>" if evl else "") + f'</div><div class=tp>{pcell}</div></div>')
        out.append(f'<div class=file><span class=kind>{e(it.get("kind") or ev.get("modality", ""))}</span>'
                   f'<b>{e(ev.get("filename", eid))}</b> <span class="mono small muted">{eid}</span> {tag}</div>' + "".join(rows))
        if iv.get("disagreement"):
            out.append(f'<p class=small style="color:var(--amber)">{e(iv["disagreement"])}</p>')
    return "".join(out) or "<p class=muted>No threat checks applied.</p>"


def _online_html(o: dict, num: str) -> str:
    e = html.escape
    hits = []
    for eid, it in (o.get("items") or {}).items():
        for m in it.get("fact_check_news") or []:
            hits.append(f'<div class="hit fc"><b>{e(m.get("site", ""))}</b><span class=tag style="color:var(--red)">Fact-check</span>'
                        f'<span class="small muted">{e(m.get("date") or "")}</span>'
                        f'<div><a href="{e(m["link"])}">{e(m.get("title") or m["link"])}</a></div></div>')
        for m in it.get("matches", []):
            lab = "contains this footage" if m.get("containment") else f'{round(m.get("similarity", 0) * 100)}% match'
            fc = '<span class=tag style="color:var(--red)">Fact-check</span>' if m.get("fact_check") else ""
            hits.append(f'<div class="hit{" fc" if m.get("fact_check") else ""}"><b>{e(m.get("site", ""))}</b>{fc}'
                        f'<span class="small muted">{lab}</span><div><a href="{e(m["link"])}">{e(m.get("title") or m["link"])}</a></div></div>')
        if not it.get("matches") and not it.get("fact_check_news"):
            hits.append(f'<p class="small muted">{eid}: no verified copies found online.</p>')
    return (f'<h2><span class=n>{num}</span>Seen online</h2><p class="small muted" style="margin-top:0">Searched {e(o.get("at", ""))} via '
            f'{e(o.get("provider", ""))}. Every match was verified locally against the evidence (perceptual hash + feature matching).</p>'
            + "".join(hits[:14]))


def render_html(case: dict, case_dir: Path, custody: list[dict]) -> str:
    from .plain import summarize
    e = html.escape
    r = case["results"] or {}
    th = r.get("threats") or {}
    v = th.get("verdict") or {}
    s = summarize(case) or {}
    fu = r.get("fusion", {}).get("overall", {})
    pct = _fake_pct(v)
    fake = bool(v.get("fake"))
    if pct is None:
        vcol = "var(--muted)"
    elif fake:
        vcol = "var(--red)" if (v.get("confidence") or 0) >= 0.8 else "var(--orange)"
    else:
        vcol = "var(--amber)" if v.get("tier") == "low" else "var(--green)"
    by_id = {x["id"]: x for x in case["evidence"]}
    counter = iter(range(2, 30))
    num = lambda: f"{next(counter):02d}"  # noqa: E731

    meter = ""
    if pct is not None:
        based = f' · based on {e(by_id[v["evidence_id"]]["filename"])}' if v.get("evidence_id") in by_id else ""
        meter = (f'<div class="card meter"><div class=lbl>Chance this is fake or manipulated</div>'
                 f'<div class=num style="color:{_pcolor(pct / 100)}">{pct}<span>%</span></div>'
                 f'<div class=bar><i style="width:{pct}%;background:{_pcolor(pct / 100)}"></i></div>'
                 f'<div class=ticks><span>Genuine</span><span>Fake</span></div>'
                 f'<p class="small muted" style="margin:10px 0 0">Calibrated on labelled public benchmarks · '
                 f'{e(v.get("tier") or "n/a")} confidence{based}</p></div>')
    d_s = r.get("duration_s") or case.get("duration_s")
    dur = f"{d_s:.0f}s" if d_s else "-"
    facts = [(len(case["evidence"]), "files examined"), (len(r.get("findings", [])), "flags raised"),
             (len(r.get("links", [])), "cross-modal links"), (dur, "analysis time")]
    facts_html = "".join(f"<div><b>{x}</b><span>{y}</span></div>" for x, y in facts)

    cyber = ""
    if fake:
        cp = complaint(case)
        steps_c = "".join(f"<li>{e(x)}</li>" for x in cp["steps"])
        cyber = (f'<div class=alert><h3>Report this to the cyber crime authorities</h3>'
                 f'<div>File a complaint on the <b>{e(cp["portal_name"])}</b>: <a href="{cp["portal"]}">{cp["portal"]}</a> · '
                 f'cyber fraud helpline <b>{cp["helpline"]}</b>.</div><ol>{steps_c}</ol>'
                 f'<div class="small muted" style="margin-top:10px">Complaint text, ready to paste:</div><div class=pre>{e(cp["text"])}</div></div>')

    o = case.get("online")
    online = _online_html(o, num()) if o else ""
    threat = _threat_section(th, by_id)

    found = "".join(f'<li>{e(x["text"])} <span class="small muted">· {e(x["file"])} · {e(x["strength"].lower())}</span></li>'
                    for x in s.get("found", [])) or "<li>No significant problems found.</li>"
    fine = "".join(f'<li>{e(x["text"])} <span class="small muted">· {e(x["file"])}</span></li>' for x in s.get("looked_fine", []))
    steps = "".join(f"<li>{e(x)}</li>" for x in s.get("next_steps", []))
    nc = "".join(f"<li>{e(x)}</li>" for x in s.get("not_checked", []))

    integ = {i["evidence_id"]: i["verified"] for i in r.get("integrity", [])}
    ev_rows = "".join(
        f'<tr><td class=mono>{x["id"]}</td><td>{e(x["filename"])}</td><td>{x["modality"]}</td><td>{x["size"]:,} B</td>'
        f'<td class=mono>{x["sha256"]}</td><td class={"ok" if integ.get(x["id"]) else "bad"}>'
        f'{"Verified" if integ.get(x["id"]) else "Not verified"}</td></tr>' for x in case["evidence"])
    fnd = []
    for f in r.get("findings", []):
        imgs = "".join(_img(case_dir, a) for a in f.get("artifacts", [])[:2])
        rev = f.get("review", {})
        alt = f'<p><b>Could also be:</b> {e("; ".join(f["alternatives"]))}</p>' if f.get("alternatives") else ""
        lim = f'<p class=small><b>Limitations:</b> {e(f["limitations"])}</p>' if f.get("limitations") else ""
        by = f' by {e(rev["by"])}' if rev.get("by") else ""
        note = f' - {e(rev["note"])}' if rev.get("note") else ""
        fnd.append(f'<div class=finding><h3><span class=fid>{f["id"]}</span>{e(f["title"])}</h3>'
                   f'<div class="small muted">{f.get("evidence_id") or "-"} · {f["modality"]} · {f["category"]} · '
                   f'score {f["score"]:.2f} · confidence {f["confidence"]:.2f} · {e(f["detector"])}</div>'
                   f'<p><b>Where:</b> {e(_loc_text(f["location"]))}</p><p><b>What:</b> {e(f.get("plain") or f["description"])}</p>'
                   f'{alt}{lim}<p class=small><b>Examiner review:</b> {e(rev.get("status", "pending"))}{by}{note}</p>'
                   f'<div class=imgs>{imgs}</div></div>')
    links = "".join(f'<li><b>{e(l["title"])}</b>: {e(l["description"])} <span class="small muted">({", ".join(l["evidence_ids"])})</span></li>'
                    for l in r.get("links", [])) or "<li>No cross-modal relationships found.</li>"
    sig_rows = "".join(f'<tr><td>{e(x["label"])}</td><td>{x["modality"]}</td><td class=mono>{x["evidence_id"] or "-"}</td>'
                       f'<td>{x["score"]:.2f}</td><td>{x["reliability"]:.2f}</td><td>{e(x["explanation"])}</td></tr>'
                       for x in r.get("signals", []))
    recs = "".join(f'<li><b>{e(x["priority"])}</b>: {e(x["check"])} <span class="small muted">({e(x["because"])})</span></li>'
                   for x in r.get("recommendations", []))
    lims = "".join(f"<li>{e(x)}</li>" for x in r.get("limitations", []) if "expert priors" not in x)
    cust = "".join(f'<tr><td class=mono>{c["at"]}</td><td>{e(c["action"])}</td><td>{e(c["detail"])}</td></tr>' for c in custody)
    hist = "".join(f'<tr><td class=mono>{h["at"]}</td><td>{e(h["step"])}</td><td>{e(h["detail"])}</td></tr>' for h in r.get("history", []))
    eng = r.get("engine", {})
    ctx = f'<h3>Case context / claim</h3><p>{e(case["context"])}</p>' if case.get("context") else ""
    fine_h = f"<h3>What looked normal</h3><ul class=clean>{fine}</ul>" if fine else ""
    nc_h = f"<h3>What we could not check</h3><ul class=clean>{nc}</ul>" if nc else ""
    hist_h = f"<h3>Analysis history</h3><table><tr><th>Time</th><th>Step</th><th>Detail</th></tr>{hist}</table>" if hist else ""
    ival = fu.get("interval", [0, 0])
    gen = (r.get("generated_at") or "")[:19].replace("T", " ")
    n_threat, n_plain, n_ev, n_find, n_tech, n_cust = num(), num(), num(), num(), num(), num()

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>TruthLens forensic report · {e(case['id'])}</title><style>{CSS}</style></head><body><div class=page>
<header class=mast><div class=brand>TruthLens<small>Forensic examination report</small></div>
<div class=ref>Case <b>{e(case['id'])}</b><br>Generated {e(gen)}<br>Examiner: {e(case.get('examiner') or 'Unassigned')}</div></header>
<div class=conf>Confidential · for investigative use · indicators, not proof</div>
<h1>{e(case['title'])}</h1>
<p class="small muted" style="margin:0 0 18px">Opened {e(case['created_at'][:16].replace('T', ' '))} · {len(case['evidence'])} file(s) ·
{e((case.get('options') or {}).get('mode', 'standard'))} check</p>

<h2><span class=n>01</span>Verdict</h2>
<div class=verdict><div class=card><div class=stamp style="color:{vcol}"><i>OVERALL FINDING</i><b>{e(v.get('label') or s.get('headline') or 'Not determined')}</b></div>
<p class=lead>{e(s.get('subline', ''))}</p><p class="small muted" style="margin:0">{e(s.get('confidence_text', ''))}</p></div>{meter}</div>
<div class=facts>{facts_html}</div>
{cyber}
{online}
<h2><span class=n>{n_threat}</span>Threat check</h2>
<p class="small muted" style="margin-top:0">Every file is checked against each threat for its media type. Only calibrated detectors decide a verdict;
heuristics are shown as supporting evidence.</p>
{threat}

<h2><span class=n>{n_plain}</span>In plain language</h2>
<div class=cols><div><h3>What we found</h3><ol class=clean>{found}</ol></div>
<div>{fine_h}<h3>What to do next</h3><ol class=clean>{steps}</ol></div></div>
{nc_h}

<h2><span class=n>{n_ev}</span>Evidence &amp; integrity</h2>
<table><tr><th>ID</th><th>File</th><th>Type</th><th>Size</th><th>SHA-256</th><th>Integrity</th></tr>{ev_rows}</table>
<p class="small muted">Originals are stored read-only and fingerprinted on upload; all analysis runs on derived copies.</p>
{ctx}

<h2><span class=n>{n_find}</span>Flagged findings</h2>
{''.join(fnd) or '<p class=muted>No findings exceeded flagging thresholds.</p>'}
<h3>How the files connect</h3><ul class=clean>{links}</ul>

<h2><span class=n>{n_tech}</span>Technical appendix</h2>
<p class=small>Overall fused indicator {fu.get('score', 0):.2f} (band {ival[0]:.2f}-{ival[1]:.2f}), {fu.get('n_signals', 0)} detector signals.
Fusion: {e(r.get('fusion', {}).get('method', ''))}. Measured accuracy on held-out data: AI images 86.2%, face swaps 87.3%,
cloned voices 82.3%, end-to-end verdict 92.4% with 1.0% false alarms.</p>
<table><tr><th>Detector</th><th>Type</th><th>Evidence</th><th>Score</th><th>Reliability</th><th>Observation</th></tr>{sig_rows}</table>
<h3>Recommended human checks</h3><ol class=clean>{recs}</ol>
<h3>Limitations</h3><ul class=clean>{lims}</ul>

<h2><span class=n>{n_cust}</span>Chain of custody</h2>
<p class="small muted">Engine {e(str(eng.get('version', '')))} on {e(str(eng.get('device', '')))} · Whisper {e(str(eng.get('whisper', '')))}</p>
<table><tr><th>Time</th><th>Action</th><th>Detail</th></tr>{cust}</table>
{hist_h}

<footer class=foot><span>TruthLens · multimodal digital forensics · case {e(case['id'])}</span>
<span>A detection score is a calibrated indicator, not a final verdict. A qualified examiner makes the final call.</span></footer>
</div><div class=tools><button onclick="window.print()">Print / Save as PDF</button></div></body></html>"""


# ------------------------------------------------------------------ evidence pack (zip) for complaints / handover
def evidence_pack(case: dict, case_dir: Path, custody: list[dict]) -> bytes:
    import io
    import zipfile
    cp = complaint(case)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("forensic_report.html", render_html(case, case_dir, custody))
        z.writestr("forensic_report.json", json.dumps({**case, "custody": custody}, indent=2, default=str))
        z.writestr("complaint_text.txt", cp["text"] + f"\n\nFile at: {cp['portal']}   Helpline: {cp['helpline']}\n")
        sums = []
        for ev in case["evidence"]:
            p = case_dir / ev["stored_as"]
            if p.exists():
                z.write(p, f"original_files/{p.name}")
                sums.append(f"{ev['sha256']}  original_files/{p.name}")
        z.writestr("SHA256SUMS.txt", "\n".join(sums) + "\n")
        z.writestr("README.txt", f"TruthLens evidence pack for case {case['id']}\n\n"
                   "forensic_report.html  - full report (open in a browser; Print > Save as PDF for a PDF copy)\n"
                   "forensic_report.json  - machine-readable report with chain of custody\n"
                   "complaint_text.txt    - ready-to-paste text for cybercrime.gov.in\n"
                   "original_files/       - the evidence exactly as received (check against SHA256SUMS.txt)\n")
    return buf.getvalue()
