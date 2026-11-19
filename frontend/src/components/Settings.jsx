import React from "react";
import { MODE_INFO, THEMES, useUI } from "../ui.jsx";

export default function Settings({ health, cases }) {
  const { prefs, setPref, toast } = useUI();
  const w = health?.warmup;
  return (
    <div style={{ maxWidth: 900 }}>
      <div className="section-head" style={{ marginTop: 0 }}><h2>Settings</h2><span className="aside small muted">Saved in this browser</span></div>
      <div className="settings-grid">
        <div className="label">Appearance</div>
        <div>
          <div className="seg">
            {THEMES.map(({ key: k, name: n }) => (
              <button key={k} className={prefs.theme === k ? "on" : ""} onClick={() => setPref("theme", k)}>{n}</button>
            ))}
          </div>
          <div className="small muted" style={{ marginTop: 6 }}>The palette button in the top bar switches themes too.</div>
        </div>

        <div className="label">Examiner name</div>
        <div>
          <input className="in" style={{ maxWidth: 360 }} value={prefs.examiner} onChange={(e) => setPref("examiner", e.target.value)} placeholder="Pre-filled on every new check" />
        </div>

        <div className="label">Default check depth</div>
        <div>
          <div className="seg">
            {Object.entries(MODE_INFO).map(([k, m]) => <button key={k} className={prefs.mode === k ? "on" : ""} onClick={() => setPref("mode", k)}>{m.name}</button>)}
          </div>
          <div className="mode-note">{MODE_INFO[prefs.mode].note}</div>
        </div>

        <div className="label">Default checks</div>
        <div>
          {[["models", "Use AI detectors", "Face-deepfake, AI-image and cloned-voice models"], ["transcribe", "Transcribe speech", "Whisper speech-to-text with word timings"], ["lipsync", "Check lip-sync", "Mouth movement vs. voice in videos"]].map(([k, t, d]) => (
            <label className="switch" key={k}>
              <input type="checkbox" checked={prefs[k]} onChange={(e) => setPref(k, e.target.checked)} />
              <span className="track" /><span><b>{t}</b><span className="small muted">{d}</span></span>
            </label>
          ))}
        </div>

        <div className="label">Analysis engine</div>
        <div>
          {health?.status !== "ok" ? <div style={{ color: "var(--red)" }}>Offline. Start the backend on port 8000.</div> : (
            <table className="t">
              <tbody>
                <tr><td className="muted" style={{ width: 170 }}>Version</td><td>{health.version}</td></tr>
                <tr><td className="muted">Compute</td><td>{health.device}</td></tr>
                <tr><td className="muted">Model warm-up</td><td>{w?.state === "ready" ? `Ready (${w.done.length}/5 loaded in ${w.seconds} s)` : `${w?.state || "idle"} (${w?.done?.length || 0}/4)`}</td></tr>
                {Object.entries(health.models || {}).map(([k, v]) => (
                  <tr key={k}><td className="muted">{k.replace(/_/g, " ")}</td><td className="mono">{v} {health.loaded?.includes(k) ? <span className="tag ok" style={{ marginLeft: 6 }}>loaded</span> : null}</td></tr>
                ))}
                <tr><td className="muted">Speech-to-text</td><td className="mono">faster-whisper {health.whisper}</td></tr>
                {Object.keys(health.errors || {}).length > 0 && <tr><td className="muted">Problems</td><td style={{ color: "var(--red)" }}>{Object.entries(health.errors).map(([k, v]) => `${k}: ${v}`).join("; ")}</td></tr>}
              </tbody>
            </table>
          )}
        </div>

        <div className="label">Data</div>
        <div>
          <div>{cases.length} case file{cases.length === 1 ? "" : "s"} stored on this machine (backend/data/cases). Evidence never leaves this computer.</div>
          <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={() => {
            try { localStorage.removeItem("truthlens.prefs"); } catch { /* ignore */ }
            toast("Preferences reset. Reloading…"); setTimeout(() => window.location.reload(), 700);
          }}>Reset preferences</button>
        </div>

        <div className="label">About</div>
        <div className="small" style={{ color: "var(--ink-2)" }}>
          TruthLens: multimodal digital forensics for the InnovEdge Hackathon 2026, Problem Statement 04.{" "}
          <a href="https://github.com/Yashaszz/truthlens" target="_blank" rel="noreferrer">Source on GitHub</a>.
        </div>
      </div>
    </div>
  );
}
