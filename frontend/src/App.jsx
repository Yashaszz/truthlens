import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.jsx";
import { ThemeIcon, useUI } from "./ui.jsx";
import Landing from "./components/Landing.jsx";
import Home from "./components/Home.jsx";
import CaseFiles from "./components/CaseFiles.jsx";
import CaseReport from "./components/CaseReport.jsx";
import Settings from "./components/Settings.jsx";

const route = () => window.location.hash.replace(/^#\/?/, "");
const THEME_WORD = { system: "Theme: follows your system", light: "Theme: light", dark: "Theme: dark" };

export default function App() {
  const ui = useUI();
  const [path, setPath] = useState(route());
  const [cases, setCases] = useState([]);
  const [health, setHealth] = useState(null);

  const refresh = useCallback(() => api.cases().then(setCases).catch(() => {}), []);
  useEffect(() => {
    const on = () => { setPath(route()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    refresh();
    const t = setInterval(refresh, 8000);
    return () => { window.removeEventListener("hashchange", on); clearInterval(t); };
  }, [refresh]);

  useEffect(() => {
    let timer;
    const poll = () => api.health()
      .then((h) => { setHealth(h); timer = setTimeout(poll, h.enabled && h.warmup?.state !== "ready" ? 2000 : 15000); })
      .catch(() => { setHealth({ status: "down" }); timer = setTimeout(poll, 4000); });
    poll();
    return () => clearTimeout(timer);
  }, []);

  const startDemo = async () => {
    try {
      ui.toast("Building the sample case…");
      const { id } = await api.demo();
      refresh();
      window.location.hash = `case/${id}`;
    } catch (e) { ui.toast(`Couldn't start the sample: ${e.message}`, "err"); }
  };

  const caseId = path.startsWith("case/") ? path.slice(5) : null;
  const page = caseId ? "case" : ["new", "cases", "settings"].includes(path) ? path : "landing";
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
                <><span className="spin" style={{ width: 10, height: 10 }} />Preparing models {warm?.done?.length || 0}/5</>
              ) : (
                <><span className="dot" style={{ background: "var(--green)" }} />Engine ready</>
              )}
            </span>
            <a className={`navlink ${page === "cases" ? "on" : ""}`} href="#/cases">Case files{cases.length ? ` (${cases.length})` : ""}</a>
            <a className={`navlink ${page === "settings" ? "on" : ""}`} href="#/settings">Settings</a>
            <button className="iconbtn" onClick={ui.cycleTheme} title={THEME_WORD[ui.prefs.theme]} aria-label={THEME_WORD[ui.prefs.theme]}>
              <ThemeIcon theme={ui.theme} pref={ui.prefs.theme} />
            </button>
            <a className="btn ink" href="#/new">New check</a>
          </nav>
        </div>
      </header>
      <main className="wrap">
        {page === "landing" && <Landing cases={cases} health={health} onDemo={startDemo} />}
        {page === "new" && <Home cases={cases} health={health} onCreated={(id) => { refresh(); window.location.hash = `case/${id}`; }} onDemo={startDemo} />}
        {page === "cases" && <CaseFiles cases={cases} onChange={refresh} />}
        {page === "case" && <CaseReport key={caseId} caseId={caseId} onDone={refresh} />}
        {page === "settings" && <Settings health={health} cases={cases} />}
      </main>
    </>
  );
}
