import React, { useRef, useState } from "react";
import { api, Kind } from "../api.jsx";
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

export default function Home({ cases, onCreated }) {
  const [files, setFiles] = useState([]);
  const [over, setOver] = useState(false);
  const [claim, setClaim] = useState("");
  const [title, setTitle] = useState("");
  const [examiner, setExaminer] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const input = useRef();

  const add = (list) => {
    const arr = [...list];
    const bad = arr.filter((f) => !kindOf(f.name));
    setErr(bad.length ? `These files can't be checked: ${bad.map((f) => f.name).join(", ")}` : "");
    setFiles((prev) => [...prev, ...arr.filter((f) => kindOf(f.name))]);
  };

  const run = async () => {
    setBusy(true); setErr("");
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("context", claim);
    fd.append("title", title || files[0]?.name.replace(/\.[^.]+$/, "") || "Untitled check");
    fd.append("examiner", examiner);
    try { onCreated((await api.createCase(fd)).id); } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <div className="home">
      <div>
        <h1>Is this photo, video or recording what it claims to be?</h1>
        <p className="intro">
          Add the media and, if you have it, the caption or claim that came with it. TruthLens checks each file for signs
          of editing, AI generation and voice cloning, compares the files against each other and the claim, and gives you
          a plain answer backed by the technical evidence.
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
                    <Kind m={kindOf(f.name)} />
                    <span className="n">{f.name}</span>
                    <span className="muted small">{size(f.size)}</span>
                    <button className="linkbtn small" onClick={() => setFiles(files.filter((_, j) => j !== i))}>remove</button>
                  </div>
                ))}
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
            <div className="fields">
              <div><label>Case name</label><input className="in" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Uses the first file name if empty" /></div>
              <div><label>Examiner</label><input className="in" value={examiner} onChange={(e) => setExaminer(e.target.value)} placeholder="Your name" /></div>
            </div>
          </div>
        </div>

        <div className="step">
          <div className="step-n">3</div>
          <div>
            <h3>Run the check</h3>
            <div className="muted small" style={{ marginBottom: 12 }}>Usually under a minute. Originals are fingerprinted (SHA-256) and never modified.</div>
            {err && <div className="notice" style={{ marginBottom: 12 }}>{err}</div>}
            <button className="btn ink big" disabled={!files.length || busy} onClick={run}>
              {busy ? <><span className="spin" style={{ borderTopColor: "var(--paper)" }} /> Uploading…</> : files.length ? `Check ${files.length} file${files.length > 1 ? "s" : ""}` : "Add a file to start"}
            </button>
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
