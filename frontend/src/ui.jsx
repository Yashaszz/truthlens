import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

/* ---------------- preferences (per browser; always optional) ---------------- */
const KEY = "truthlens.prefs";
const DEFAULTS = { theme: "system", examiner: "", mode: "standard", models: true, transcribe: true, lipsync: true };

function readPrefs() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return { ...DEFAULTS }; }
}
function writePrefs(p) {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private mode etc. */ }
}

const UI = createContext(null);
export const useUI = () => useContext(UI);

export const THEMES = [
  { key: "light", name: "Paper", colors: ["#f3efe6", "#1e1c19", "#a3321f"] },
  { key: "dark", name: "Night", colors: ["#171612", "#ece5d6", "#e2765e"] },
  { key: "violet", name: "Midnight violet", colors: ["#120c24", "#d946ef", "#d9f99d"] },
  { key: "ocean", name: "Ocean", colors: ["#0a1520", "#22d3ee", "#fde68a"] },
  { key: "forest", name: "Forest", colors: ["#0d150f", "#4ade80", "#fef08a"] },
  { key: "rose", name: "Rose", colors: ["#faf0ef", "#2a1215", "#e11d48"] },
  { key: "contrast", name: "High contrast", colors: ["#000000", "#ffffff", "#ffe14d"] },
  { key: "system", name: "Match system", colors: ["#f3efe6", "#171612", "#7b7467"] },
];

function resolveTheme(t) {
  if (t && t !== "system") return t;
  try { return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; } catch { return "light"; }
}

export function UIProvider({ children }) {
  const [prefs, setPrefs] = useState(readPrefs);
  const [toasts, setToasts] = useState([]);
  const [dialog, setDialog] = useState(null);
  const resolver = useRef(null);

  const theme = resolveTheme(prefs.theme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (prefs.theme !== "system") return;
    let mq;
    try { mq = window.matchMedia("(prefers-color-scheme: dark)"); } catch { return; }
    const on = () => document.documentElement.setAttribute("data-theme", resolveTheme("system"));
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [prefs.theme]);

  const setPref = useCallback((k, v) => setPrefs((p) => { const n = { ...p, [k]: v }; writePrefs(n); return n; }), []);
  const cycleTheme = () => setPref("theme", { system: "light", light: "dark", dark: "system" }[prefs.theme] || "system");

  const toast = useCallback((msg, kind = "ok") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);

  const confirm = useCallback((opts) => new Promise((res) => { resolver.current = res; setDialog(opts); }), []);
  const close = (v) => { setDialog(null); resolver.current?.(v); };

  return (
    <UI.Provider value={{ prefs, setPref, theme, cycleTheme, toast, confirm }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind === "err" ? "err" : ""}`}>{t.msg}</div>)}
      </div>
      {dialog && (
        <div className="dialog-back" onClick={() => close(false)}>
          <div className="dialog" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>{dialog.title}</h3>
            <div className="muted">{dialog.body}</div>
            <div className="btns">
              <button className="btn ghost" onClick={() => close(false)} autoFocus>Cancel</button>
              <button className={`btn ${dialog.danger ? "danger" : "ink"}`} onClick={() => close(true)}>{dialog.confirmLabel || "OK"}</button>
            </div>
          </div>
        </div>
      )}
    </UI.Provider>
  );
}

export function ThemeIcon({ theme, pref }) {
  if (pref === "system") return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="3" y="4" width="18" height="13" rx="1" /><path d="M8 21h8M12 17v4" /></svg>
  );
  return theme === "dark" ? (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" /></svg>
  ) : (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
  );
}

export const MODE_INFO = {
  quick: { name: "Quick", note: "Samples 1 frame per second, first 60 s of video and 90 s of audio. Good for a first look; about half the time." },
  standard: { name: "Standard", note: "2 frames per second, up to 2 minutes of video and 3 minutes of audio. The balanced default." },
  thorough: { name: "Thorough", note: "4 frames per second, up to 5 minutes, voice checked every second. Slower, but catches brief edits." },
};
