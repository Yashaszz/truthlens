import React from "react";
import { Kind } from "../api.jsx";

const WORD = { strong: "Strong signs", indicators: "Possible manipulation", inconclusive: "No clear answer", none: "Nothing found" };

export function StatusTag({ c }) {
  if (c.status === "failed") return <span className="tag strong">Failed</span>;
  if (c.status !== "complete") return <span className="small"><span className="spin" style={{ width: 10, height: 10, verticalAlign: -1 }} /> Checking…</span>;
  return c.assessment ? <span className={`tag b-${c.assessment}`}>{WORD[c.assessment]}</span> : null;
}

export default function CaseFiles({ cases }) {
  return (
    <div>
      <div className="section-head" style={{ marginTop: 0 }}>
        <h2>Case files</h2>
        <span className="aside"><a className="btn ink" href="#/">New check</a></span>
      </div>
      {cases.length === 0 ? <div className="empty">No checks yet. Start one from <a href="#/">New check</a>.</div> : (
        <table className="t" style={{ fontSize: 14.5 }}>
          <thead><tr><th>Case</th><th>Files</th><th>Result</th><th>Opened</th></tr></thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => { window.location.hash = `case/${c.id}`; }}>
                <td><a href={`#/case/${c.id}`} style={{ fontWeight: 600, color: "var(--ink)" }}>{c.title}</a><div className="mono muted">{c.id}</div></td>
                <td><div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>{c.modalities.map((m) => <Kind key={m} m={m} />)}</div>
                  <div className="small muted">{c.evidence_count} file{c.evidence_count === 1 ? "" : "s"}</div></td>
                <td><StatusTag c={c} /></td>
                <td className="small muted">{c.created_at.slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
