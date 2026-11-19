import React, { useState } from "react";
import { CountUp } from "./Motion.jsx";

export const STATUS = {
  detected: ["Detected", "var(--red)"],
  likely: ["Likely", "var(--orange)"],
  at_risk: ["At risk", "var(--amber)"],
  not_detected: ["Not found", "var(--green)"],
  not_applicable: ["Not applicable", "var(--muted)"],
  not_checked: ["Not checked", "var(--muted)"],
};

export function VerdictMeter({ verdict }) {
  if (!verdict || verdict.confidence == null) return null;
  const fakeChance = verdict.fake ? verdict.confidence : 1 - verdict.confidence;
  const pct = Math.round(fakeChance * 100);
  const color = fakeChance >= 0.8 ? "var(--red)" : fakeChance >= 0.6 ? "var(--orange)" : fakeChance > 0.4 ? "var(--amber)" : "var(--green)";
  return (
    <div className="vmeter">
      <div className="label" style={{ marginBottom: 10 }}>Chance this is fake or manipulated</div>
      <div className="vnum" style={{ color }}><CountUp value={pct} /><span>%</span></div>
      <div className="vbar"><div style={{ width: `${pct}%`, background: color }} /></div>
      <div className="vticks"><span>Genuine</span><span>Fake</span></div>
      <div className="small muted" style={{ marginTop: 8 }}>
        Calibrated on labelled benchmarks{verdict.tier ? ` · ${verdict.tier} confidence` : ""}
      </div>
    </div>
  );
}

export default function ThreatMatrix({ item, compact = false, onFinding }) {
  const [showAll, setShowAll] = useState(!compact);
  if (!item?.matrix) return null;
  const rows = item.matrix;
  const shown = showAll ? rows : rows.filter((m) => ["detected", "likely", "at_risk"].includes(m.status));
  return (
    <div className="tmatrix">
      {shown.length === 0 && <div className="small muted" style={{ padding: "8px 0" }}>No threats detected in this file.</div>}
      {shown.map((m) => {
        const [word, color] = STATUS[m.status] || STATUS.not_checked;
        const dim = m.status === "not_applicable" || m.status === "not_checked";
        return (
          <div key={m.key} className={`trow ${dim ? "dim" : ""}`}>
            <span className="tchip" style={{ color, borderColor: color }}>{word}</span>
            <div className="tname">
              <b>{m.name}</b>
              <div className="small muted">{m.desc}</div>
              {(m.evidence?.length > 0 || m.note) && (
                <ul className="tev">
                  {m.evidence.map((e, i) => <li key={i}>{e}</li>)}
                  {m.note && <li className="muted">{m.note}</li>}
                </ul>
              )}
              {onFinding && m.finding_ids?.length > 0 && (
                <button className="linkbtn small" onClick={() => onFinding(m.finding_ids[0])}>show evidence</button>
              )}
            </div>
            <div className="tp">
              {m.p != null && !dim ? (
                <>
                  <span className="mono">{Math.round(m.p * 100)}%</span>
                  <div className="meter"><div style={{ width: `${m.p * 100}%`, background: color }} /></div>
                </>
              ) : <span className="muted small">–</span>}
            </div>
          </div>
        );
      })}
      {compact && rows.length > shown.length && (
        <button className="linkbtn small" style={{ marginTop: 8 }} onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show only threats found" : `Show all ${rows.length} threat checks`}
        </button>
      )}
    </div>
  );
}
