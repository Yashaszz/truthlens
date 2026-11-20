import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, API } from "../api.jsx";
import { useUI } from "../ui.jsx";

const Shield = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M12 8v5M12 16.5v.01" />
  </svg>
);

/* Panel that prepares a cybercrime complaint: ready-to-paste text, evidence pack, portal + helpline. */
export function CyberPanel({ caseId, onClose }) {
  const ui = useUI();
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.complaint(caseId).then(setD).catch((e) => setErr(e.message)); }, [caseId]);
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(d.text); ui.toast("Complaint text copied"); }
    catch { ui.toast("Select the text and copy it manually", "err"); }
  };
  return createPortal(
    <div className="dialog-back" onClick={onClose}>
      <div className="dialog cyber" role="dialog" aria-modal="true" aria-labelledby="cyber-h" onClick={(e) => e.stopPropagation()}>
        <div className="cyber-head">
          <span className="cyber-ic"><Shield /></span>
          <div>
            <h3 id="cyber-h">Report to cybercrime</h3>
            <div className="small muted">National Cyber Crime Reporting Portal, Government of India · helpline 1930</div>
          </div>
          <button className="linkbtn" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto", fontSize: 20 }}>×</button>
        </div>
        {err && <div style={{ color: "var(--red)" }}>{err}</div>}
        {!d && !err && <div className="muted"><span className="spin" /> Preparing the complaint…</div>}
        {d && (
          <>
            {!d.fake && (
              <div className="cyber-note">TruthLens did not find this media to be fake ({d.verdict}). You can still report it if it is being used to harm or defraud someone.</div>
            )}
            <ol className="cyber-steps">{d.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            <div className="label" style={{ marginTop: 14 }}>Complaint text, ready to paste</div>
            <textarea className="in mono cyber-text" readOnly value={d.text} rows={8} onFocus={(e) => e.target.select()} />
            <div className="cyber-actions">
              <button className="btn ink" onClick={copy}>Copy text</button>
              <a className="btn" href={`${API}/api/cases/${caseId}/evidence-pack.zip`}>Download evidence pack</a>
              <a className="btn cyber-go" href={d.portal} target="_blank" rel="noreferrer">Open cybercrime.gov.in ↗</a>
              <a className="btn ghost" href={`tel:${d.helpline}`}>Call {d.helpline}</a>
            </div>
            <div className="small muted" style={{ marginTop: 10 }}>
              The evidence pack holds the forensic report, the original files with SHA-256 hashes, and this complaint text. TruthLens never files anything for you:
              you submit the complaint yourself on the official portal.
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function CyberButton({ caseId, fake }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={`btn ${fake ? "cyber-go" : "ghost"}`} onClick={() => setOpen(true)}><Shield /> Report to cybercrime</button>
      {open && <CyberPanel caseId={caseId} onClose={() => setOpen(false)} />}
    </>
  );
}

export function CyberBanner({ caseId }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="cyber-banner">
      <span className="cyber-ic"><Shield /></span>
      <div style={{ minWidth: 0 }}>
        <b>This looks fake. Is it being used to harm, impersonate or defraud someone?</b>
        <div className="small muted">Report it on the National Cyber Crime Reporting Portal. We prepare the complaint text and an evidence pack for you.</div>
      </div>
      <button className="btn cyber-go" onClick={() => setOpen(true)}>Report it</button>
      {open && <CyberPanel caseId={caseId} onClose={() => setOpen(false)} />}
    </div>
  );
}
