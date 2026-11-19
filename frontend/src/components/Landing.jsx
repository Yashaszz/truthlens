import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.jsx";
import { CountUp } from "./Motion.jsx";
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

function AccuracyStrip() {
  const [a, setA] = useState(null);
  useEffect(() => { api.accuracy().then(setA).catch(() => {}); }, []);
  if (!a || !a.ai_image) return null;
  const cell = (k, title, sub) => a[k] && (
    <div>
      <div className="label">{title}</div>
      <div className="n">{(a[k].heldout["acc@0.5"] * 100).toFixed(1)}%</div>
      <div className="small">accuracy on held-out data · AUC {a[k].heldout.auc.toFixed(2)}</div>
      <div className="was">{sub}</div>
    </div>
  );
  const ps = a.ai_image.per_set || {};
  return (
    <section className="section">
      <div className="section-head"><h2>Measured, not guessed</h2><span className="aside small muted">Benchmarked on public labelled datasets the detectors weren't tuned on</span></div>
      <div className="acc-grid">
        {cell("ai_image", "AI-generated images", `${Math.round((ps.GenImage?.["acc@0.5"] || 0) * 100)}% on GenImage, ${Math.round((ps.CommunityForensics?.["acc@0.5"] || 0) * 100)}% on 2025 generators · previous model: 60%`)}
        {cell("face_swap", "Face swaps & synthetic faces", "Trained head on Community Forensics features · previous model: 48% (chance)")}
        {cell("voice", "Cloned voices", "Real-world deepfakes + ElevenLabs clones · previous model: AUC 0.40")}
      </div>
    </section>
  );
}

const TICK = [["Face swaps", "DFDC-winning video detector"], ["AI images", "96% on photoreal generators"], ["Cloned voices", "AUC 0.91 cross-dataset"],
  ["Seen online", "exact copies + fact-checks"], ["Chain of custody", "SHA-256 on ingest"], ["Lip-sync", "mouth vs voice"], ["Metadata", "C2PA · EXIF · XMP"]];

export default function Landing({ cases, health, onDemo }) {
  const card = useRef(null);
  const tilt = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
    card.current?.style.setProperty("--ry", `${-14 + x * 22}deg`);
    card.current?.style.setProperty("--rx", `${8 - y * 18}deg`);
  };
  const untilt = () => { card.current?.style.removeProperty("--ry"); card.current?.style.removeProperty("--rx"); };
  const done = cases.filter((c) => c.status === "complete");
  const files = cases.reduce((n, c) => n + (c.evidence_count || 0), 0);
  const times = done.map((c) => c.duration_s).filter(Boolean);
  const avg = times.length ? times.reduce((a, b) => a + b, 0) / times.length : null;
  const flagged = done.filter((c) => ["strong", "indicators"].includes(c.assessment)).length;
  const ready = health?.status === "ok" && (!health.enabled || health.warmup?.state === "ready");

  return (
    <div>
      <section className="hero2" onMouseMove={tilt} onMouseLeave={untilt}>
        <div className="copy">
          <h1><span className="spark">✦</span>Spot the fake<br />before it <span className="lit">spreads</span></h1>
          <p className="lede">
            Deepfake videos, AI images, cloned voices and misleading captions, examined in seconds with detectors
            measured on public benchmarks, and an explanation of every flag.
          </p>
          <div className="cta-row">
            <a className="cta" href="#/new"><span>Start a check</span><span className="arr">→</span></a>
            <button className="cta ghost" onClick={onDemo}><span>Try a sample case</span><span className="arr">▶</span></button>
          </div>
          <div className="hero-meta">
            <span><i className={ready ? "" : "off"} />{ready ? "Engine ready" : health?.status === "ok" ? "Engine warming up" : "Engine offline"}</span>
            {health?.device && <span>{health.device}</span>}
            <span>Press N for a new check</span>
          </div>
        </div>
        <div className="stage" aria-hidden="true">
          <span className="blob" />
          <span className="blob b2" />
          <div className="glass" ref={card}>
            <div className="g-top"><span>TRUTHLENS · SCAN</span><span>TL-0427</span></div>
            <div className="bars">
              <div>FACE SWAP</div><span><i /></span>
              <div>VOICE CLONE</div><span><i /></span>
              <div>AI IMAGE</div><span><i /></span>
            </div>
            <div className="face" />
            <div className="scan" />
            <div className="res">CHANCE FAKE<b>98%</b><span className="pill">FAKE</span></div>
          </div>
        </div>
      </section>
      <div className="ticker" aria-hidden="true">
        <div>
          {[...TICK, ...TICK].map((t, i) => <span key={i}>✦ <b>{t[0]}</b> {t[1]}</span>)}
        </div>
      </div>

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

      <AccuracyStrip />

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
          <div><div className="n"><CountUp value={cases.length} /></div><div className="small muted">checks run</div></div>
          <div><div className="n"><CountUp value={files} /></div><div className="small muted">files examined</div></div>
          <div><div className="n"><CountUp value={flagged} /></div><div className="small muted">cases with warning signs</div></div>
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
