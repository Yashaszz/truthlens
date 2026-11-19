import React, { useEffect, useState, useCallback } from "react";
import { api, BAND } from "./api.js";
import NewCase from "./components/NewCase.jsx";
import CaseView from "./components/CaseView.jsx";

const route = () => window.location.hash.replace(/^#\/?/, "");

export default function App() {
  const [path, setPath] = useState(route());
  const [cases, setCases] = useState([]);
  const [health, setHealth] = useState(null);

  const refresh = useCallback(() => api.cases().then(setCases).catch(() => {}), []);
  useEffect(() => {
    const on = () => setPath(route());
    window.addEventListener("hashchange", on);
    refresh();
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
    const t = setInterval(refresh, 5000);
    return () => { window.removeEventListener("hashchange", on); clearInterval(t); };
  }, [refresh]);

  const caseId = path.startsWith("case/") ? path.slice(5) : null;
  const go = (p) => { window.location.hash = p; };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="14" cy="14" r="9" fill="none" stroke="var(--accent)" strokeWidth="3" />
            <path d="M21 21l7 7" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" />
            <path d="M9 14h2l1.5-3 3 6 1.5-3h2" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
          </svg>
          <div>
            <h1>TruthLens</h1>
            <div className="tag">Multimodal media forensics</div>
          </div>
        </div>
        <div style={{ padding: "0 16px 12px" }}>
          <button className="btn primary" style={{ width: "100%" }} onClick={() => go("")}>+ New investigation</button>
        </div>
        <div className="muted small" style={{ padding: "4px 18px" }}>CASES</div>
        <div className="case-list">
          {cases.length === 0 && <div className="muted small" style={{ padding: 10 }}>No cases yet.</div>}
          {cases.map((c) => (
            <div key={c.id} className={`case-item ${c.id === caseId ? "active" : ""}`} onClick={() => go(`case/${c.id}`)}>
              <div className="t">{c.title}</div>
              <div className="small muted mono">{c.id}</div>
              <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center", flexWrap: "wrap" }}>
                {c.status !== "complete" ? (
                  <span className="chip">{c.status === "failed" ? "failed" : <><span className="spin" style={{ width: 10, height: 10 }} /> {c.status}</>}</span>
                ) : c.assessment ? (
                  <span className="chip"><span className="sw" style={{ background: BAND[c.assessment]?.color }} />{BAND[c.assessment]?.short}</span>
                ) : null}
                <span className="small muted">{c.modalities.join(" · ")}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="health">
          {health == null ? "Connecting…" : health.status === "ok" ? (
            <>
              <div><span className="dot" style={{ background: "var(--green)" }} />Engine v{health.version} online</div>
              <div>Compute: {health.device}</div>
              <div>Models: {health.enabled ? "pretrained + classical" : "classical only"}</div>
            </>
          ) : <div><span className="dot" style={{ background: "var(--red)" }} />Backend offline: start the API on :8000</div>}
        </div>
      </aside>
      <main className="main">
        {caseId ? <CaseView key={caseId} caseId={caseId} onChange={refresh} /> : <NewCase onCreated={(id) => { refresh(); go(`case/${id}`); }} />}
      </main>
    </div>
  );
}
