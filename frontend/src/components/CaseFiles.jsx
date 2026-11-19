import React, { useMemo, useState } from "react";
import { api, Kind } from "../api.jsx";
import { useUI } from "../ui.jsx";

const WORD = { strong: "Strong signs", indicators: "Possible manipulation", inconclusive: "No clear answer", none: "Nothing found" };

export function StatusTag({ c }) {
  if (c.status === "failed") return <span className="tag strong">Failed</span>;
  if (c.status !== "complete") return <span className="small"><span className="spin" style={{ width: 10, height: 10, verticalAlign: -1 }} /> Checking…</span>;
  if (c.verdict && c.verdict_conf != null) {
    const cls = c.verdict_fake ? (c.verdict_conf >= 0.8 ? "strong" : "moderate") : c.verdict.startsWith("Leaning") ? "weak" : "ok";
    return <span className={`tag ${cls}`}>{c.verdict} · {Math.round(c.verdict_conf * 100)}%</span>;
  }
  return c.assessment ? <span className={`tag b-${c.assessment}`}>{WORD[c.assessment]}</span> : null;
}

const FILTERS = [["all", "All cases"], ["strong", "Strong signs"], ["indicators", "Possible"], ["inconclusive", "No clear answer"], ["none", "Nothing found"]];

export default function CaseFiles({ cases, onChange }) {
  const ui = useUI();
  const [q, setQ] = useState("");
  const [band, setBand] = useState("all");
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState("new");

  const counts = useMemo(() => {
    const c = { all: cases.length };
    cases.forEach((x) => { if (x.assessment) c[x.assessment] = (c[x.assessment] || 0) + 1; });
    return c;
  }, [cases]);

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let l = cases.filter((c) =>
      (band === "all" || c.assessment === band) &&
      (kind === "all" || c.modalities.includes(kind)) &&
      (!needle || `${c.title} ${c.id} ${c.examiner || ""}`.toLowerCase().includes(needle)));
    if (sort === "old") l = [...l].reverse();
    if (sort === "risk") l = [...l].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    if (sort === "name") l = [...l].sort((a, b) => a.title.localeCompare(b.title));
    return l;
  }, [cases, q, band, kind, sort]);

  const remove = async (c, e) => {
    e.stopPropagation();
    const ok = await ui.confirm({ title: `Delete “${c.title}”?`, body: "This permanently removes the case, its stored evidence copies, results and custody log from this machine. It can't be undone.", confirmLabel: "Delete case", danger: true });
    if (!ok) return;
    try { await api.deleteCase(c.id); ui.toast("Case deleted"); onChange(); } catch (err) { ui.toast(err.message, "err"); }
  };

  return (
    <div>
      <div className="section-head" style={{ marginTop: 0 }}>
        <h2>Case files</h2>
        <span className="aside"><a className="btn ink" href="#/new">New check</a></span>
      </div>
      <div className="stats">
        {FILTERS.map(([k, n]) => (
          <button key={k} className={band === k ? "on" : ""} onClick={() => setBand(k)}>
            <div className={`n ${k !== "all" ? `c-${k}` : ""}`}>{counts[k] || 0}</div>
            <div className="small muted">{n}</div>
          </button>
        ))}
      </div>
      <div className="toolbar">
        <input className="in" placeholder="Search by name, case ID or examiner" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="in" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="File type">
          <option value="all">Any file type</option><option value="image">With photos</option><option value="video">With video</option>
          <option value="audio">With audio</option><option value="text">With text</option>
        </select>
        <select className="in" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          <option value="new">Newest first</option><option value="old">Oldest first</option><option value="risk">Most suspicious first</option><option value="name">By name</option>
        </select>
        <span className="small muted" style={{ marginLeft: "auto" }}>{list.length} of {cases.length}</span>
      </div>
      {cases.length === 0 ? <div className="empty">No checks yet. Start one from <a href="#/new">New check</a>.</div>
        : list.length === 0 ? <div className="empty">No cases match these filters.</div> : (
          <table className="t" style={{ fontSize: 14.5 }}>
            <thead><tr><th>Case</th><th>Files</th><th>Result</th><th>Review</th><th>Opened</th><th /></tr></thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id} className="click" onClick={() => { window.location.hash = `case/${c.id}`; }}>
                  <td><a href={`#/case/${c.id}`} style={{ fontWeight: 600, color: "var(--ink)" }}>{c.title}</a>
                    <div className="mono muted">{c.id}{c.mode && c.mode !== "standard" ? ` · ${c.mode}` : ""}</div></td>
                  <td><div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>{c.modalities.map((m) => <Kind key={m} m={m} />)}</div>
                    <div className="small muted">{c.evidence_count} file{c.evidence_count === 1 ? "" : "s"}</div></td>
                  <td><StatusTag c={c} />{c.score != null && <div className="mono muted tiny" style={{ marginTop: 3 }}>score {c.score.toFixed(2)}</div>}</td>
                  <td className="small muted">{c.status === "complete" ? `${c.reviewed}/${c.findings} flags` : "–"}</td>
                  <td className="small muted">{c.created_at.slice(0, 16).replace("T", " ")}<div>{c.examiner}</div></td>
                  <td><button className="linkbtn small" style={{ color: "var(--red)" }} onClick={(e) => remove(c, e)}>delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  );
}
