import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, Kind } from "../api.jsx";
import { MODE_INFO, useUI } from "../ui.jsx";
import { StatusTag } from "./CaseFiles.jsx";

const EXT = {
  image: ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"],
  video: ["mp4", "mov", "avi", "mkv", "webm", "m4v"],
  audio: ["wav", "mp3", "m4a", "flac", "ogg", "aac", "opus"],
  text: ["txt", "md", "srt", "vtt", "json"],
};
const kindOf = (name) => {
  const e = name.split(".").pop().toLowerCase();
  return Object.keys(EXT).find((k) => EXT[k].includes(e));
};
const size = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);

function Toggle({ checked, onChange, title, children }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      <span><b>{title}</b><span className="small muted">{children}</span></span>
    </label>
  );
}

function Thumb({ file }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (kindOf(file.name) !== "image") return;
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return url ? <img className="th" src={url} alt="" /> : null;
}

export default function Home({ cases, health, onCreated, onDemo }) {
  const ui = useUI();
  const p = ui.prefs;
  const [files, setFiles] = useState([]);
  const [over, setOver] = useState(false);
  const [claim, setClaim] = useState("");
  const [title, setTitle] = useState("");
  const [examiner, setExaminer] = useState(p.examiner);
  const [mode, setMode] = useState(p.mode);
  const [models, setModels] = useState(p.models);
  const [transcribe, setTranscribe] = useState(p.transcribe);
  const [lipsync, setLipsync] = useState(p.lipsync);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef();

  const add = (list) => {
    const arr = [...list];
    const bad = arr.filter((f) => !kindOf(f.name));
    setErr(bad.length ? `These files can't be checked: ${bad.map((f) => f.name).join(", ")}` : "");
    setFiles((prev) => [...prev, ...arr.filter((f) => kindOf(f.name))]);
  };

  const kinds = useMemo(() => new Set(files.map((f) => kindOf(f.name))), [files]);
  const estimate = useMemo(() => {
    if (!files.length) return null;
    const per = { image: 2, video: 12, audio: 6, text: 0.5 };
    const mult = { quick: 0.55, standard: 1, thorough: 2.4 }[mode];
    const mb = files.reduce((n, f) => n + f.size, 0) / 1e6;
    let s = files.reduce((n, f) => n + per[kindOf(f.name)], 0) * mult + mb * 0.15 + 2;
    if (!models) s *= 0.6;
    return s < 60 ? `about ${Math.max(5, Math.round(s / 5) * 5)} seconds` : `about ${Math.round(s / 60)} minute${s >= 90 ? "s" : ""}`;
  }, [files, mode, models]);

  const run = async () => {
    setBusy(true); setErr("");
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("context", claim);
    fd.append("title", title || files[0]?.name.replace(/\.[^.]+$/, "") || "Untitled check");
    fd.append("examiner", examiner);
    fd.append("options", JSON.stringify({ mode, models, transcribe, lipsync }));
    if (examiner && examiner !== p.examiner) ui.setPref("examiner", examiner);
    try { onCreated((await api.createCase(fd)).id); } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <div className="home">
      <div>
        <h1>Is this photo, video or recording what it claims to be?</h1>
        <p className="intro">
          Add the media and, if you have it, the caption or claim that came with it. You'll get a plain answer backed by
          the technical evidence. <button className="linkbtn" onClick={onDemo}>Or try a sample case first.</button>
        </p>

        <div className="step">
          <div className="step-n">1</div>
          <div>
            <h3>Add the files</h3>
            <div className="muted small">Photos, videos, voice notes or audio, and any transcript or text file. Several files can be checked together.</div>
            <div className={`drop ${over ? "over" : ""}`} onClick={() => input.current.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
              <b>Drop files here</b> <span className="muted">or click to choose</span>
              <div className="tiny muted" style={{ marginTop: 6 }}>JPG · PNG · WEBP · MP4 · MOV · WEBM · WAV · MP3 · M4A · TXT · SRT</div>
              <input ref={input} type="file" multiple hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
            </div>
            {files.length > 0 && (
              <div className="filelist">
                {files.map((f, i) => (
                  <div className="file" key={i}>
                    <Thumb file={f} />
                    <Kind m={kindOf(f.name)} />
                    <span className="n">{f.name}</span>
                    <span className="muted small">{size(f.size)}</span>
                    <button className="linkbtn small" onClick={() => setFiles(files.filter((_, j) => j !== i))}>remove</button>
                  </div>
                ))}
                <div className="small muted" style={{ marginTop: 8, display: "flex", justifyContent: "space-between" }}>
                  <span>{files.length} file{files.length > 1 ? "s" : ""} · {size(files.reduce((n, f) => n + f.size, 0))}</span>
                  <button className="linkbtn small" onClick={() => setFiles([])}>clear all</button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="step">
          <div className="step-n">2</div>
          <div>
            <h3>What is being claimed? <span className="muted small" style={{ fontFamily: "var(--sans)", fontWeight: 400 }}>(optional)</span></h3>
            <div className="muted small">Paste the caption, post or message. Put exact quotes in "double quotes": we check whether they are really said.</div>
            <textarea className="in" style={{ marginTop: 10 }} value={claim} onChange={(e) => setClaim(e.target.value)}
              placeholder={'e.g. Minister filmed today at the Pune rally saying "we will cancel the election".'} />
            <div className="small muted" style={{ marginTop: 4 }}>
              {(claim.match(/["“”][^"“”]{8,}["“”]/g) || []).length} quote(s) detected
              {/\b(19|20)\d{2}\b/.test(claim) ? " · a year is mentioned, so dates will be checked" : ""}
            </div>
            <div className="fields">
              <div><label>Case name</label><input className="in" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Uses the first file name if empty" /></div>
              <div><label>Examiner</label><input className="in" value={examiner} onChange={(e) => setExaminer(e.target.value)} placeholder="Your name (remembered)" /></div>
            </div>
          </div>
        </div>

        <div className="step">
          <div className="step-n">3</div>
          <div>
            <h3>How thorough?</h3>
            <div className="seg" style={{ marginTop: 8 }} role="radiogroup" aria-label="Check depth">
              {Object.entries(MODE_INFO).map(([k, m]) => (
                <button key={k} role="radio" aria-checked={mode === k} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>{m.name}</button>
              ))}
            </div>
            <div className="mode-note">{MODE_INFO[mode].note}</div>
            <details className="more" style={{ marginTop: 12 }}>
              <summary>More options <span className="muted small">{[!models && "AI detectors off", !transcribe && "no transcript", !lipsync && "no lip-sync"].filter(Boolean).join(", ") || "all checks on"}</span></summary>
              <Toggle checked={models} onChange={setModels} title="Use AI detectors"> Face-deepfake, AI-image and cloned-voice models. Turn off for classical forensics only (faster, fully explainable).</Toggle>
              <Toggle checked={transcribe} onChange={setTranscribe} title="Transcribe speech"> Needed to check quotes and to time the lip-sync check.</Toggle>
              <Toggle checked={lipsync} onChange={setLipsync} title="Check lip-sync"> Compares mouth movement with the voice in videos.</Toggle>
            </details>
          </div>
        </div>

        <div className="step">
          <div className="step-n">4</div>
          <div>
            <h3>Run the check</h3>
            <div className="muted small" style={{ marginBottom: 12 }}>
              {estimate ? <>Estimated time: <b style={{ color: "var(--ink)" }}>{estimate}</b>. </> : ""}Originals are fingerprinted (SHA-256) and never modified.
              {kinds.has("video") && !transcribe && " Without a transcript, the quote check is skipped."}
            </div>
            {err && <div className="notice" style={{ marginBottom: 12 }}>{err}</div>}
            <button className="btn ink big" disabled={!files.length || busy || health?.status === "down"} onClick={run}>
              {busy ? <><span className="spin" style={{ borderTopColor: "var(--paper)" }} /> Uploading…</> : files.length ? `Check ${files.length} file${files.length > 1 ? "s" : ""}` : "Add a file to start"}
            </button>
            {health?.status === "down" && <div className="small" style={{ color: "var(--red)", marginTop: 8 }}>The analysis engine is offline. Start the backend on port 8000.</div>}
          </div>
        </div>
      </div>

      <aside>
        <div className="aside-box">
          <h3>What you get back</h3>
          <ol>
            <li><b>A plain answer</b>: what was found, how sure we are, and what to check next.</li>
            <li><b>Marked-up evidence</b>: suspicious areas, moments and words highlighted in each file.</li>
            <li><b>How the files relate</b>: does the voice match the lips? Is the quote really said?</li>
            <li><b>Technical appendix</b>: every detector, score, limitation and the chain of custody.</li>
            <li><b>A report</b> you can download and share.</li>
          </ol>
        </div>
        {cases.length > 0 && (
          <div className="recent">
            <div className="label" style={{ marginBottom: 6 }}>Recent case files</div>
            {cases.slice(0, 5).map((c) => (
              <a key={c.id} href={`#/case/${c.id}`}>
                <div className="t">{c.title}</div>
                <div className="small muted" style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 3 }}>
                  <StatusTag c={c} /> <span>{c.created_at.slice(0, 16).replace("T", " ")}</span>
                </div>
              </a>
            ))}
            <a href="#/cases" className="small" style={{ color: "var(--blue)", borderBottom: 0 }}>All case files →</a>
          </div>
        )}
      </aside>
    </div>
  );
}
