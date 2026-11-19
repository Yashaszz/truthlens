import React, { useState } from "react";
import { api, fileUrl, fmtTs, scoreColor } from "../api.js";
import { Meter } from "./Charts.jsx";
import { ModChip } from "./CaseView.jsx";

export function locText(l) {
  if (!l) return "–";
  switch (l.type) {
    case "regions": return (l.regions || []).map((r) => `${r.label || ""} (${r.bbox.join(", ")})`).join("; ") || "Image regions";
    case "frames": return "Frames at " + (l.frames || []).slice(0, 8).map((f) => fmtTs(f.t)).join(", ");
    case "segments": return (l.segments || []).slice(0, 8).map((s) => `${fmtTs(s.start)}–${fmtTs(s.end)}`).join(", ");
    case "timestamps": return "At " + (l.times || []).slice(0, 8).map(fmtTs).join(", ");
    case "metadata": return "Metadata: " + (l.fields || []).join(", ");
    case "text": return `Text (${l.source})` + (l.closest_segment?.start != null ? ` · closest speech ${fmtTs(l.closest_segment.start)}` : "");
    case "series": return "Across the frame timeline";
    default: return "Whole file";
  }
}

const STATUSES = [["confirmed", "Confirm"], ["needs-follow-up", "Follow up"], ["dismissed", "Dismiss"]];

function FindingCard({ c, f, onUpdate, onLocate, setZoom }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(f.review?.note || "");
  const [busy, setBusy] = useState(false);
  const setStatus = async (status) => {
    setBusy(true);
    try { await api.review(c.id, f.id, { status, note }); await onUpdate(); } finally { setBusy(false); }
  };
  const rev = f.review || {};
  return (
    <div className="finding" style={{ borderLeft: `4px solid ${scoreColor(f.score)}` }}>
      <div className="finding-head" onClick={() => setOpen(!open)}>
        <span className="fid">{f.id}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600 }}>{f.title}</div>
          <div className="small muted" style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 3 }}>
            <span className="mono">{f.evidence_id || "case"}</span><ModChip m={f.modality} /><span>{f.category}</span><span>· {locText(f.location)}</span>
            {rev.status && rev.status !== "pending" && <span className="chip">reviewed: {rev.status}</span>}
          </div>
        </div>
        <div style={{ width: 150 }}>
          <div className="small" style={{ display: "flex", justifyContent: "space-between" }}><span className="muted">indicator</span><b>{f.score.toFixed(2)}</b></div>
          <Meter value={f.score} />
          <div className="small" style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}><span className="muted">confidence</span><span>{f.confidence.toFixed(2)}</span></div>
          <Meter value={f.confidence} color="var(--accent)" />
        </div>
      </div>
      {open && (
        <div className="finding-body">
          <div className="kv">
            <div>Indicator</div><div>{f.description}</div>
            <div>Flagged location</div><div>{locText(f.location)} {f.evidence_id && <button className="btn sm" style={{ marginLeft: 8 }} onClick={() => onLocate(f)}>Show in evidence →</button>}</div>
            <div>Detector</div><div className="mono">{f.detector}</div>
            {f.limitations && <><div>Limitations</div><div>{f.limitations}</div></>}
            {f.alternatives?.length > 0 && <><div>Alternative explanations</div><div><ul style={{ margin: 0, paddingLeft: 18 }}>{f.alternatives.map((a, i) => <li key={i}>{a}</li>)}</ul></div></>}
            {f.related?.length > 0 && <><div>Related findings</div><div className="mono">{f.related.join(", ")}</div></>}
          </div>
          {f.artifacts?.length > 0 && (
            <div className="thumbs">
              {f.artifacts.map((a) => <img key={a} src={fileUrl(c.id, a)} alt={a} onClick={() => setZoom(fileUrl(c.id, a))} />)}
            </div>
          )}
          <div className="review">
            <span className="muted small" style={{ marginRight: 4 }}>Examiner review:</span>
            {STATUSES.map(([k, n]) => (
              <button key={k} disabled={busy} className={`btn sm ${rev.status === k ? `on-${k}` : ""}`} onClick={() => setStatus(k)}>{n}</button>
            ))}
            <input className="in" style={{ flex: 1, minWidth: 200, padding: "5px 9px" }} placeholder="Note (saved to chain of custody)"
              value={note} onChange={(e) => setNote(e.target.value)} />
            {rev.at && <span className="muted small">{rev.by} · {rev.at.replace("T", " ")}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Findings({ c, onUpdate, onLocate }) {
  const [mod, setMod] = useState("all");
  const [zoom, setZoom] = useState(null);
  const all = c.results.findings;
  const mods = ["all", ...new Set(all.map((f) => f.modality))];
  const list = all.filter((f) => mod === "all" || f.modality === mod);
  const reviewed = all.filter((f) => f.review?.status && f.review.status !== "pending").length;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div className="seg-toggle">
          {mods.map((m) => <button key={m} className={mod === m ? "on" : ""} onClick={() => setMod(m)}>{m}</button>)}
        </div>
        <div className="muted small">{reviewed}/{all.length} reviewed by examiner</div>
      </div>
      {list.length === 0 && <div className="card empty">No findings for this filter.</div>}
      {list.map((f) => <FindingCard key={f.id} c={c} f={f} onUpdate={onUpdate} onLocate={onLocate} setZoom={setZoom} />)}
      {zoom && <div className="lightbox" onClick={() => setZoom(null)}><img src={zoom} alt="artifact" /></div>}
    </div>
  );
}
