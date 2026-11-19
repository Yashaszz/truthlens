import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.jsx";
import Home from "./components/Home.jsx";
import CaseFiles from "./components/CaseFiles.jsx";
import CaseReport from "./components/CaseReport.jsx";

const route = () => window.location.hash.replace(/^#\/?/, "");

export default function App() {
  const [path, setPath] = useState(route());
  const [cases, setCases] = useState([]);
  const [health, setHealth] = useState(null);

  const refresh = useCallback(() => api.cases().then(setCases).catch(() => {}), []);
  useEffect(() => {
    const on = () => { setPath(route()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    refresh();
    return () => window.removeEventListener("hashchange", on);
  }, [refresh]);

  useEffect(() => {
    let timer;
    const poll = () => api.health()
      .then((h) => { setHealth(h); if (h.enabled && h.warmup?.state !== "ready") timer = setTimeout(poll, 2000); })
      .catch(() => { setHealth({ status: "down" }); timer = setTimeout(poll, 4000); });
    poll();
    return () => clearTimeout(timer);
  }, []);

  const caseId = path.startsWith("case/") ? path.slice(5) : null;
  const page = caseId ? "case" : path === "cases" ? "cases" : "home";
  const warm = health?.warmup;

  return (
    <>
      <header className="masthead">
        <div className="masthead-in">
          <a className="wordmark" href="#/">
            <b>TruthLens</b>
            <span>Media evidence examination</span>
          </a>
          <nav>
            <span className="engine" title={health?.device || ""}>
              {health == null ? "Connecting…" : health.status !== "ok" ? (
                <><span className="dot" style={{ background: "var(--red)" }} />Engine offline</>
              ) : health.enabled && warm?.state !== "ready" ? (
                <><span className="spin" style={{ width: 10, height: 10 }} />Preparing models {warm?.done?.length || 0}/4</>
              ) : (
                <><span className="dot" style={{ background: "var(--green)" }} />Ready</>
              )}
            </span>
            <a className={`navlink ${page === "cases" ? "on" : ""}`} href="#/cases">Case files{cases.length ? ` (${cases.length})` : ""}</a>
            <a className="btn ink" href="#/">New check</a>
          </nav>
        </div>
      </header>
      <main className="wrap">
        {page === "home" && <Home cases={cases} onCreated={(id) => { refresh(); window.location.hash = `case/${id}`; }} />}
        {page === "cases" && <CaseFiles cases={cases} />}
        {page === "case" && <CaseReport key={caseId} caseId={caseId} onDone={refresh} />}
      </main>
    </>
  );
}
