import React from "react";
import { StatusTag } from "./CaseFiles.jsx";

const KINDS = [
  { k: "Photos", c: "var(--c-image)", p: "Edited, composited or AI-generated pictures.",
    li: ["Compression and camera-grain maps", "Copied-and-pasted areas", "Generator metadata and AI-image detector", "Face manipulation"] },
  { k: "Video", c: "var(--c-video)", p: "Face swaps, splices and re-encoded footage.",
    li: ["Face check on sampled frames", "Hidden cuts and frozen frames", "Blending around the face", "Container and encoder traces"] },
  { k: "Voice & audio", c: "var(--c-audio)", p: "Cloned voices and cut-together recordings.",
    li: ["Synthetic-voice detector", "Silent gaps and room-tone jumps", "Pitch and bandwidth clues", "Full transcript with timings"] },
  { k: "Captions & claims", c: "var(--c-text)", p: "Text that misdescribes real media.",
    li: ["Are the quoted words really said?", "Do dates match the file?", "Does the caption fit the speech?", "Supplied transcripts vs audio"] },
];

const FLOW = [
  ["Ingest", "Files are fingerprinted (SHA-256) and stored read-only. Originals are never touched."],
  ["Analyse", "Each file runs through classical forensics and pretrained detectors for its media type."],
  ["Correlate", "Lips vs voice, quotes vs speech, dates vs metadata, photos vs video frames."],
  ["Review", "Every flag is located and explained; an examiner confirms or dismisses it."],
  ["Report", "A plain summary plus the full technical record and chain of custody."],
];

const PRINCIPLES = [
  ["An indicator, not a verdict", "Scores come with a likely range and say when the checks disagree. Nothing is presented as proof."],
  ["Every flag has an address", "A region of the picture, a frame, a second of audio or a word in the caption, so anyone can look for themselves."],
  ["Innocent explanations included", "Each finding lists what else could cause it, such as compression, filters or a noisy room."],
  ["The human decides", "Examiner decisions and notes go into the chain of custody alongside the machine's results."],
];

export default function Landing({ cases, health, onDemo }) {
  const done = cases.filter((c) => c.status === "complete");
  const files = cases.reduce((n, c) => n + (c.evidence_count || 0), 0);
  const times = done.map((c) => c.duration_s).filter(Boolean);
  const avg = times.length ? times.reduce((a, b) => a + b, 0) / times.length : null;
  const flagged = done.filter((c) => ["strong", "indicators"].includes(c.assessment)).length;
  const ready = health?.status === "ok" && (!health.enabled || health.warmup?.state === "ready");

  return (
    <div>
      <section className="hero">
        <div>
          <div className="kicker">Multimodal digital forensics</div>
          <h1>Evidence you can <em>explain</em>, not just a score.</h1>
          <p>
            TruthLens examines photos, video, voice recordings and the captions that come with them. It shows you
            what looks manipulated, exactly where, how sure it is, and what else could explain it.
          </p>
          <div className="ctas">
            <a className="btn ink big" href="#/new">Start a check</a>
            <button className="btn big" onClick={onDemo}>Try a sample case</button>
            <span className="small muted" style={{ marginLeft: 6 }}>
              {ready ? "Engine ready" : health?.status === "ok" ? "Engine warming up…" : "Engine offline"}{health?.device ? ` · ${health.device}` : ""}
            </span>
          </div>
        </div>
        <div className="specimen" aria-hidden="true">
          <span className="clip" />
          <div className="label">Case file · specimen</div>
          <div className="stamp c-indicators" style={{ margin: "12px 0 14px" }}>
            <div className="label">Overall finding</div>
            <div className="h" style={{ fontSize: 21 }}>Signs of possible manipulation</div>
          </div>
          <div className="row"><b>1</b><span>Part of the picture was copied and pasted elsewhere in it.</span><span className="tag strong">Strong</span></div>
          <div className="row"><b>2</b><span>The quote in the caption is not said in the recording.</span><span className="tag moderate">Moderate</span></div>
          <div className="row"><b>3</b><span>Perfectly silent gaps at 0:09 suggest cut-and-paste audio.</span><span className="tag moderate">Moderate</span></div>
          <div className="row" style={{ color: "var(--muted)" }}><span style={{ color: "var(--green)", fontWeight: 700 }}>✓</span><span>Lip movements match the voice.</span><span /></div>
        </div>
      </section>

      <section className="band-strip">
        {KINDS.map((x) => (
          <div key={x.k}>
            <span className="kind" style={{ color: x.c }}><i style={{ background: "currentColor" }} />Checks</span>
            <h3>{x.k}</h3>
            <p>{x.p}</p>
            <ul>{x.li.map((l) => <li key={l}>{l}</li>)}</ul>
          </div>
        ))}
      </section>

      <section className="section">
        <div className="section-head"><h2>How a check works</h2><span className="aside small muted">Usually under a minute on a laptop GPU</span></div>
        <div className="flow">{FLOW.map(([h, p]) => <div key={h}><h3>{h}</h3><p>{p}</p></div>)}</div>
      </section>

      <section className="section">
        <div className="section-head"><h2>Built for forensic trust</h2></div>
        <div className="principles">{PRINCIPLES.map(([h, p]) => <div key={h}><h3>{h}</h3><p>{p}</p></div>)}</div>
      </section>

      <section className="section">
        <div className="section-head"><h2>On this machine</h2><span className="aside"><a href="#/cases" className="small">All case files →</a></span></div>
        <div className="statline">
          <div><div className="n">{cases.length}</div><div className="small muted">checks run</div></div>
          <div><div className="n">{files}</div><div className="small muted">files examined</div></div>
          <div><div className="n">{flagged}</div><div className="small muted">cases with warning signs</div></div>
          <div><div className="n">{avg != null ? `${avg.toFixed(0)} s` : "–"}</div><div className="small muted">average time per check</div></div>
        </div>
        {cases.length > 0 && (
          <table className="t" style={{ marginTop: 16 }}>
            <tbody>
              {cases.slice(0, 4).map((c) => (
                <tr key={c.id} className="click" onClick={() => { window.location.hash = `case/${c.id}`; }}>
                  <td style={{ fontWeight: 600 }}>{c.title}</td><td><StatusTag c={c} /></td>
                  <td className="small muted">{c.evidence_count} file{c.evidence_count === 1 ? "" : "s"} · {c.created_at.slice(0, 16).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {health?.models && (
          <div className="small muted" style={{ marginTop: 14 }}>
            Detectors: {Object.values(health.models).join(" · ")} · Whisper {health.whisper}. All run locally; nothing is uploaded to third parties.
          </div>
        )}
      </section>

      <footer className="footer">
        <span>TruthLens · InnovEdge Hackathon 2026 · Problem Statement 04</span>
        <a href="https://github.com/Yashaszz/truthlens" target="_blank" rel="noreferrer">Source on GitHub</a>
        <span style={{ marginLeft: "auto" }}>A detection score is an indicator, not a final verdict.</span>
      </footer>
    </div>
  );
}
