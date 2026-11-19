import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.jsx";
import { CountUp } from "./Motion.jsx";
import { StatusTag } from "./CaseFiles.jsx";

/* ---------- scroll reveal: adds .in to [data-reveal] elements when they enter the viewport ---------- */
function useReveal(deps = []) {
  useEffect(() => {
    const els = [...document.querySelectorAll("[data-reveal]:not(.seen)")];
    if (!("IntersectionObserver" in window)) { els.forEach((e) => e.classList.add("seen")); return; }
    const io = new IntersectionObserver((ents) => ents.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("seen"); io.unobserve(e.target); }
    }), { threshold: 0.18 });
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, deps);
}

const ICONS = {
  photo: <svg viewBox="0 0 48 48"><rect x="6" y="9" width="36" height="30" rx="4" /><circle cx="17" cy="19" r="4" /><path d="M6 33l11-10 9 8 6-5 10 9" /><path className="pulse" d="M30 6l3 3M38 6l-3 3" /></svg>,
  video: <svg viewBox="0 0 48 48"><rect x="5" y="11" width="28" height="26" rx="4" /><path d="M33 20l10-6v20l-10-6z" /><circle cx="19" cy="22" r="5" /><path d="M12 33c2-4 12-4 14 0" /></svg>,
  audio: <svg viewBox="0 0 48 48"><path d="M6 24h4M14 16v16M20 10v28M26 18v12M32 13v22M38 20v8M42 24h1" /></svg>,
  text: <svg viewBox="0 0 48 48"><path d="M8 10h32M8 18h24M8 26h28M8 34h16" /><path d="M34 30l6 6M40 30l-6 6" /></svg>,
  ingest: <svg viewBox="0 0 48 48"><path d="M24 6v24M15 21l9 9 9-9" /><path d="M8 32v8h32v-8" /></svg>,
  analyse: <svg viewBox="0 0 48 48"><circle cx="21" cy="21" r="12" /><path d="M30 30l11 11" /><path d="M15 21h12M21 15v12" /></svg>,
  correlate: <svg viewBox="0 0 48 48"><circle cx="12" cy="14" r="5" /><circle cx="36" cy="14" r="5" /><circle cx="24" cy="36" r="5" /><path d="M16 17l6 14M32 17l-6 14M17 14h14" /></svg>,
  review: <svg viewBox="0 0 48 48"><path d="M10 25l9 9 19-20" /><rect x="5" y="5" width="38" height="38" rx="6" /></svg>,
  report: <svg viewBox="0 0 48 48"><path d="M12 5h18l8 8v30H12z" /><path d="M30 5v8h8M18 24h14M18 31h14M18 38h8" /></svg>,
};

const KINDS = [
  { k: "Photos", icon: "photo", c: "var(--c-image)", p: "AI-generated, face-swapped, edited or composited pictures.",
    li: ["AI-image ensemble · 96% on photoreal", "Face-swap head", "Copy-move & metadata forensics"] },
  { k: "Video", icon: "video", c: "var(--c-video)", p: "Face-swap deepfakes, lip-sync fakes and spliced footage.",
    li: ["DFDC-winning video detector", "Lip-sync vs voice", "Cuts, freezes, re-encoding"] },
  { k: "Voice", icon: "audio", c: "var(--c-audio)", p: "Cloned and synthetic voices, cut-together recordings.",
    li: ["Voice-clone ensemble", "Splice & room-tone checks", "Full transcript with timings"] },
  { k: "Claims", icon: "text", c: "var(--c-text)", p: "Captions that misdescribe real media, recycled old footage.",
    li: ["Quotes vs what is said", "Dates vs file metadata", "Seen online + fact-checks"] },
];

const FLOW = [
  ["ingest", "Ingest", "Fingerprinted (SHA-256), stored read-only."],
  ["analyse", "Analyse", "Benchmarked detectors per media type."],
  ["correlate", "Correlate", "Lips vs voice, quotes vs speech, web copies."],
  ["review", "Review", "Every flag located and explained."],
  ["report", "Report", "Plain verdict + full technical record."],
];

const TRUST = [
  ["01", "An indicator, not a verdict", "Calibrated probabilities. Close calls say which way they lean."],
  ["02", "Every flag has an address", "A region, a frame, a second of audio or a word in the caption."],
  ["03", "Innocent explanations", "Each finding lists what else could cause it."],
  ["04", "The human decides", "Examiner decisions go into the chain of custody."],
];

function Ring({ value, label, sub, was }) {
  const R = 62, C = 2 * Math.PI * R;
  return (
    <div className="ringcard" data-reveal>
      <svg viewBox="0 0 150 150" className="ring">
        <defs>
          <linearGradient id={`g-${label.replace(/[^a-z]/gi, "")}`} x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="var(--blob-3)" /><stop offset="1" stopColor="var(--blob-2)" />
          </linearGradient>
        </defs>
        <circle cx="75" cy="75" r={R} className="track" />
        <circle cx="75" cy="75" r={R} className="arc" stroke={`url(#g-${label.replace(/[^a-z]/gi, "")})`}
          style={{ strokeDasharray: C, "--off": C * (1 - value / 100), "--c": C }} />
      </svg>
      <div className="ring-num"><CountUp value={value} decimals={1} /><span>%</span></div>
      <div className="ring-label">{label}</div>
      <div className="ring-sub">{sub}</div>
      {was != null && (
        <div className="race">
          <div><span>before</span><i style={{ "--w": `${was}%` }} className="old" /><b>{was}%</b></div>
          <div><span>now</span><i style={{ "--w": `${value}%` }} /><b>{value.toFixed(0)}%</b></div>
        </div>
      )}
    </div>
  );
}

function Accuracy() {
  const [a, setA] = useState(null);
  useEffect(() => { api.accuracy().then(setA).catch(() => {}); }, []);
  useReveal([a]);
  if (!a || !a.ai_image) return null;
  const ps = a.ai_image.per_set || {};
  const photoreal = ((ps.GenImage?.["acc@0.5"] || 0) + (ps.CommunityForensics?.["acc@0.5"] || 0)) / 2 * 100;
  return (
    <section className="lsec">
      <div className="lhead" data-reveal><span className="eyebrow">✦ Measured, not guessed</span><h2>Benchmarked on data the detectors never saw</h2></div>
      <div className="rings">
        <Ring value={photoreal} label="AI images" sub="photoreal generators · held-out" was={60} />
        {a.face_swap && <Ring value={a.face_swap.heldout["acc@0.5"] * 100} label="Face swaps" sub={`AUC ${a.face_swap.heldout.auc.toFixed(2)} · held-out split`} was={48} />}
        {a.voice && <Ring value={a.voice.heldout["acc@0.5"] * 100} label="Cloned voices" sub={`AUC ${a.voice.heldout.auc.toFixed(2)} · cross-dataset`} was={44} />}
      </div>
    </section>
  );
}

function Pipeline() {
  return (
    <section className="lsec">
      <div className="lhead" data-reveal><span className="eyebrow">✦ How a check works</span><h2>Five steps, usually under a minute</h2></div>
      <div className="pipe" data-reveal>
        <div className="pipe-line"><span className="pipe-pulse" /></div>
        {FLOW.map(([ic, h, p], i) => (
          <div className="node" key={h} style={{ "--i": i }}>
            <div className="node-dot">{ICONS[ic]}</div>
            <div className="node-n">0{i + 1}</div>
            <h3>{h}</h3>
            <p>{p}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const TICK = [["Face swaps", "DFDC-winning video detector"], ["AI images", "96% on photoreal generators"], ["Cloned voices", "AUC 0.91 cross-dataset"],
  ["Seen online", "exact copies + fact-checks"], ["Chain of custody", "SHA-256 on ingest"], ["Lip-sync", "mouth vs voice"], ["Metadata", "C2PA · EXIF · XMP"]];

export default function Landing({ cases, health, onDemo }) {
  const card = useRef(null);
  useReveal([cases.length]);
  const tilt = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
    card.current?.style.setProperty("--ry", `${-14 + x * 22}deg`);
    card.current?.style.setProperty("--rx", `${8 - y * 18}deg`);
  };
  const untilt = () => { card.current?.style.removeProperty("--ry"); card.current?.style.removeProperty("--rx"); };
  const lift = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
    e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
  };
  const done = cases.filter((c) => c.status === "complete");
  const files = cases.reduce((n, c) => n + (c.evidence_count || 0), 0);
  const times = done.map((c) => c.duration_s).filter(Boolean);
  const avg = times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0;
  const flagged = done.filter((c) => c.verdict_fake).length;
  const ready = health?.status === "ok" && (!health.enabled || health.warmup?.state === "ready");

  return (
    <div className="landing">
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
        <div>{[...TICK, ...TICK].map((t, i) => <span key={i}>✦ <b>{t[0]}</b> {t[1]}</span>)}</div>
      </div>

      <section className="lsec">
        <div className="lhead" data-reveal><span className="eyebrow">✦ What it catches</span><h2>Four kinds of fake, one check</h2></div>
        <div className="kinds">
          {KINDS.map((x, i) => (
            <a key={x.k} href="#/new" className="kcard" data-reveal style={{ "--i": i, "--kc": x.c }} onMouseMove={lift}>
              <span className="kglow" />
              <span className="kicon">{ICONS[x.icon]}</span>
              <h3>{x.k}</h3>
              <p>{x.p}</p>
              <ul>{x.li.map((l) => <li key={l}>{l}</li>)}</ul>
              <span className="kgo">Check one →</span>
            </a>
          ))}
        </div>
      </section>

      <Accuracy />
      <Pipeline />

      <section className="lsec">
        <div className="lhead" data-reveal><span className="eyebrow">✦ Built for forensic trust</span><h2>Explains itself. Never claims proof.</h2></div>
        <div className="trust">
          {TRUST.map(([n, h, p], i) => (
            <div key={n} className="tcard" data-reveal style={{ "--i": i }} onMouseMove={lift}>
              <span className="kglow" />
              <span className="tnum">{n}</span>
              <h3>{h}</h3>
              <p>{p}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="lsec">
        <div className="lhead" data-reveal><span className="eyebrow">✦ Live on this engine</span><h2>Running right now</h2></div>
        <div className="live" data-reveal>
          <div><b><CountUp value={cases.length} /></b><span>checks run</span></div>
          <div><b><CountUp value={files} /></b><span>files examined</span></div>
          <div><b className="hot"><CountUp value={flagged} /></b><span>fakes caught</span></div>
          <div><b><CountUp value={avg} /><small>s</small></b><span>average per check</span></div>
        </div>
        {cases.length > 0 && (
          <div className="recent-row" data-reveal>
            {cases.slice(0, 4).map((c) => (
              <a key={c.id} href={`#/case/${c.id}`} className="rcard" onMouseMove={lift}>
                <span className="kglow" />
                <b>{c.title}</b>
                <StatusTag c={c} />
                <span className="tiny muted">{c.evidence_count} file{c.evidence_count === 1 ? "" : "s"} · {c.created_at.slice(5, 16).replace("T", " ")}</span>
              </a>
            ))}
          </div>
        )}
      </section>

      <section className="cta-band" data-reveal>
        <span className="blob b3" aria-hidden="true" />
        <h2>Got something suspicious?</h2>
        <p>Drop in a photo, video, voice note or caption. You'll have an answer before it's forwarded again.</p>
        <div className="cta-row" style={{ justifyContent: "center" }}>
          <a className="cta" href="#/new"><span>Start a check</span><span className="arr">→</span></a>
          <button className="cta ghost" onClick={onDemo}><span>Try a sample</span><span className="arr">▶</span></button>
        </div>
      </section>

      <footer className="footer">
        <span>TruthLens · InnovEdge Hackathon 2026 · Problem Statement 04</span>
        <a href="https://github.com/Yashaszz/truthlens" target="_blank" rel="noreferrer">Source on GitHub</a>
        <span style={{ marginLeft: "auto" }}>A detection score is an indicator, not a final verdict.</span>
      </footer>
    </div>
  );
}
