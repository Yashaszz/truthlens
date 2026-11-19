import React, { useRef, useState } from "react";
import { api, MODALITY_COLOR } from "../api.js";

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
const human = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(0)} KB`);

export default function NewCase({ onCreated }) {
  const [files, setFiles] = useState([]);
  const [over, setOver] = useState(false);
  const [title, setTitle] = useState("");
  const [examiner, setExaminer] = useState("");
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef();

  const add = (list) => {
    const arr = [...list];
    const bad = arr.filter((f) => !kindOf(f.name));
    setErr(bad.length ? `Unsupported: ${bad.map((f) => f.name).join(", ")}` : "");
    setFiles((prev) => [...prev, ...arr.filter((f) => kindOf(f.name))]);
  };

  const submit = async () => {
    setBusy(true); setErr("");
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("title", title); fd.append("examiner", examiner); fd.append("context", context);
    try {
      const { id } = await api.createCase(fd);
      onCreated(id);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>New investigation</h2>
          <div className="muted">Ingest → Analyze → Correlate → Review → Report</div>
        </div>
      </div>
      <div className="grid g-main">
        <div className="card">
          <h3>1 · Evidence</h3>
          <div className={`drop ${over ? "over" : ""}`} onClick={() => input.current.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
            <div style={{ fontSize: 16, fontWeight: 600 }}>Drop media here or click to browse</div>
            <div className="muted small" style={{ marginTop: 6 }}>
              Images (JPG, PNG, WebP) · Video (MP4, MOV, WebM) · Audio (WAV, MP3, M4A) · Text (TXT, SRT, VTT)
            </div>
            <input ref={input} type="file" multiple hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          </div>
          {files.map((f, i) => {
            const k = kindOf(f.name);
            return (
              <div key={i} className="file-row">
                <span className="chip"><span className="sw" style={{ background: MODALITY_COLOR[k] }} />{k}</span>
                <span className="n">{f.name}</span>
                <span className="muted small">{human(f.size)}</span>
                <button className="btn sm" onClick={() => setFiles(files.filter((_, j) => j !== i))}>Remove</button>
              </div>
            );
          })}
          <label className="f">Caption, claims or context to verify (quotes in "double quotes" are checked against speech)</label>
          <textarea className="in" value={context} onChange={(e) => setContext(e.target.value)}
            placeholder={'e.g. BREAKING: Minister filmed today saying "we will cancel the election" at a rally in Pune, March 2026.'} />
          <div className="grid g2">
            <div>
              <label className="f">Case title</label>
              <input className="in" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Viral rally clip" />
            </div>
            <div>
              <label className="f">Examiner</label>
              <input className="in" value={examiner} onChange={(e) => setExaminer(e.target.value)} placeholder="Your name" />
            </div>
          </div>
          {err && <div style={{ color: "var(--red)", marginTop: 12 }}>{err}</div>}
          <div style={{ marginTop: 18, display: "flex", gap: 12, alignItems: "center" }}>
            <button className="btn primary" disabled={!files.length || busy} onClick={submit}>
              {busy ? <><span className="spin" /> Uploading…</> : `Analyze ${files.length || ""} file${files.length === 1 ? "" : "s"}`}
            </button>
            <span className="muted small">Files are hashed (SHA-256) and stored read-only on ingest.</span>
          </div>
        </div>
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card">
            <h3>What gets analysed</h3>
            <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
              <li><b style={{ color: "var(--c-image)" }}>Image</b>: ELA, noise residual, JPEG/DCT grid, copy-move, EXIF/generator metadata, AI-image &amp; face classifiers</li>
              <li><b style={{ color: "var(--c-video)" }}>Video</b>: per-frame face deepfake ViT, face blending, scene cuts, frozen frames, container metadata</li>
              <li><b style={{ color: "var(--c-audio)" }}>Audio</b>: wav2vec2 voice-spoof classifier, MFCC/ZCR features, splice &amp; noise-floor checks, Whisper transcript</li>
              <li><b style={{ color: "var(--c-text)" }}>Text</b>: quotes vs transcript, caption topic, dates vs metadata, supplied transcripts</li>
              <li><b style={{ color: "var(--c-cross)" }}>Cross-modal</b>: lip-sync check, temporal convergence, face/voice patterns, image↔video provenance</li>
            </ul>
          </div>
          <div className="notice">
            TruthLens reports <b>indicators with calibrated uncertainty</b>, not verdicts. Every flag links to its location,
            supporting evidence, limitations and alternative explanations for human review.
          </div>
        </div>
      </div>
    </div>
  );
}
