import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.jsx";
import { THEMES, useUI } from "./ui.jsx";
import Landing from "./components/Landing.jsx";
import Home from "./components/Home.jsx";
import CaseFiles from "./components/CaseFiles.jsx";
import CaseReport from "./components/CaseReport.jsx";
import Settings from "./components/Settings.jsx";

const route = () => window.location.hash.replace(/^#\/?/, "");

function ThemePicker() {
  const ui = useUI();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const off = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", off);
    return () => document.removeEventListener("pointerdown", off);
  }, []);
  const cur = THEMES.find((t) => t.key === ui.prefs.theme) || THEMES[0];
  return (
    <span className="picker" ref={ref}>
      <button className="iconbtn" onClick={() => setOpen(!open)} title={`Colour theme: ${cur.name}`} aria-label="Colour theme" aria-expanded={open}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5c0-4-4-7.4-9-7.4z" />
          <circle cx="7.5" cy="11" r="1.2" /><circle cx="10.5" cy="7.2" r="1.2" /><circle cx="15" cy="7.4" r="1.2" />
        </svg>
      </button>
      {open && (
        <div className="picker-pop" role="menu">
          {THEMES.map((t) => (
            <button key={t.key} role="menuitemradio" aria-checked={ui.prefs.theme === t.key} className={`swatch ${ui.prefs.theme === t.key ? "on" : ""}`}
              onClick={() => { ui.setPref("theme", t.key); setOpen(false); }}>
              <span className="chip3">{t.colors.map((c) => <i key={c} style={{ background: c }} />)}</span>{t.name}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

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

  // "N" anywhere (outside text fields) starts a new check
  useEffect(() => {
    const key = (e) => {
      if (e.key.toLowerCase() !== "n" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target.closest?.("input, textarea, select, [contenteditable=true]")) return;
      window.location.hash = "new";
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

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
            <ThemePicker />
            <a className="btn ink" href="#/new">New check</a>
          </nav>
        </div>
      </header>
      <main className="wrap page-enter" key={page + (caseId || "")}>
        {page === "landing" && <Landing cases={cases} health={health} onDemo={startDemo} />}
        {page === "new" && <Home cases={cases} health={health} onCreated={(id) => { refresh(); window.location.hash = `case/${id}`; }} onDemo={startDemo} />}
        {page === "cases" && <CaseFiles cases={cases} onChange={refresh} />}
        {page === "case" && <CaseReport key={caseId} caseId={caseId} onDone={refresh} />}
        {page === "settings" && <Settings health={health} cases={cases} />}
      </main>
      {page !== "new" && (
        <a className="fab" href="#/new" title="Start a new check (shortcut: N)">
          <span className="plus">+</span>New check<kbd>N</kbd>
        </a>
      )}
    </>
  );
}
