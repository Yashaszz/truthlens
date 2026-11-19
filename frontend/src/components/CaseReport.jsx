import React, { useEffect, useState } from "react";
import { api, Kind, KIND, scoreColor } from "../api.jsx";
import { Meter, Scale } from "./Charts.jsx";
import { FileSection } from "./Evidence.jsx";

const EFFECT = {
  strengthens: ["Adds weight", "var(--red)"],
  weakens: ["Reduces concern", "var(--green)"],
  context: ["Context", "var(--blue)"],
};

function stagesFor(c) {
  const st = [{ label: "Fingerprinting and securing the files", keys: ["ingested", "Case created"] }];
  c.evidence.filter((e) => e.modality !== "text").forEach((e) => {
    if (e.modality === "image") st.push({ label: `Examining photo: ${e.filename}`, keys: [`Examining photo: ${e.filename}`] });
    if (e.modality === "audio") st.push({ label: `Listening to audio: ${e.filename}`, keys: [`Listening to audio: ${e.filename}`] });
    if (e.modality === "video") st.push({ label: `Watching video and checking lip-sync: ${e.filename}`, keys: [`Watching video: ${e.filename}`, `soundtrack of ${e.filename}`, `lip-sync in ${e.filename}`] });
  });
  st.push({ label: "Reading the caption and checking it against the media", keys: ["Reading the caption"] });
  st.push({ label: "Comparing what the files say about each other", keys: ["Comparing what"] });
  st.push({ label: "Writing the report", keys: ["Writing the report"] });
  return st;
}

function Working({ c }) {
  const stages = stagesFor(c);
  const msg = c.progress?.message || "";
  let cur = 0;
  stages.forEach((s, i) => { if (s.keys.some((k) => msg.includes(k))) cur = i; });
  return (
    <div className="sheet work">
      <h2 style={{ fontSize: 24 }}>Checking {c.evidence.length} file{c.evidence.length > 1 ? "s" : ""}…</h2>
      <div className="muted">This usually takes under a minute. You can leave this page; the result is saved in Case files.</div>
      <ul className="checklist">
        {stages.map((s, i) => (
          <li key={i} className={i < cur ? "done" : i === cur ? "cur" : ""}>
            <span className="box2">{i < cur ? "✓" : i === cur ? <span className="spin" style={{ width: 10, height: 10 }} /> : ""}</span>{s.label}
          </li>
        ))}
      </ul>
      <div className="progress"><div style={{ width: `${c.progress?.pct || 0}%` }} /></div>
    </div>
  );
}

export default function CaseReport({ caseId, onDone }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState("");
  const [hl, setHl] = useState(null);
  const [zoom, setZoom] = useState(null);

  const load = () => api.getCase(caseId).then(setC).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [caseId]);
  useEffect(() => {
    if (!c || c.status === "complete" || c.status === "failed") return;
    const t = setInterval(load, 1200);
    return () => clearInterval(t);
  }, [c?.status]);
  useEffect(() => { if (c?.status === "complete") onDone?.(); }, [c?.status]);

  const goFinding = (fid) => {
    setHl(fid);
    setTimeout(() => document.getElementById(`f-${fid}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
  };

  if (err) return <div className="empty">{err}. <a href="#/cases">Back to case files</a></div>;
  if (!c) return <div className="empty"><span className="spin" /></div>;
  const r = c.results;
  const s = c.summary;

  return (
    <div>
      <div className="crumbs"><a href="#/cases">Case files</a> / <span className="mono">{c.id}</span></div>
      <div className="case-head">
        <div>
          <h1>{c.title}</h1>
          <div className="muted small">Opened {c.created_at.replace("T", " ").slice(0, 16)} · Examiner: {c.examiner} · {c.evidence.length} file{c.evidence.length > 1 ? "s" : ""}{r && ` · checked in ${r.duration_s} s`}</div>
        </div>
        {r && (
          <div className="actions">
            <a className="btn ink" href={`/api/cases/${c.id}/report.html?download=true`}>Download report</a>
            <a className="btn" href={`/api/cases/${c.id}/report.html`} target="_blank" rel="noreferrer">Printable view</a>
            <a className="btn ghost" href={`/api/cases/${c.id}/report.json`}>Raw data (JSON)</a>
          </div>
        )}
      </div>

      {c.status === "failed" && (
        <div className="sheet"><h2 style={{ color: "var(--red)" }}>The check could not finish</h2><p>{c.progress?.message}</p>
          <details className="more"><summary>Error details</summary><pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>{c.error}</pre></details></div>
      )}
      {c.status !== "complete" && c.status !== "failed" && <Working c={c} />}

      {r && s && (
        <div className="layout">
          <nav className="toc">
            <div className="label">On this page</div>
            <a href="#summary" onClick={(e) => jump(e, "summary")}>Summary</a>
            <a href="#files" onClick={(e) => jump(e, "files")}>The files</a>
            {c.evidence.map((e) => <a key={e.id} className="sub" href={`#file-${e.id}`} onClick={(ev) => jump(ev, `file-${e.id}`)}>{KIND[e.modality]}: {e.filename}</a>)}
            <a href="#connections" onClick={(e) => jump(e, "connections")}>How the files connect</a>
            <a href="#appendix" onClick={(e) => jump(e, "appendix")}>Technical appendix</a>
            <a href="#custody" onClick={(e) => jump(e, "custody")}>Chain of custody</a>
          </nav>

          <div style={{ minWidth: 0 }}>
            {/* ---------------- summary ---------------- */}
            <section id="summary" className="sheet" style={{ scrollMarginTop: 90 }}>
              {c.context && (
                <div style={{ borderLeft: "3px solid var(--rule)", paddingLeft: 14, marginBottom: 20 }}>
                  <div className="label">Claim checked</div>
                  <div style={{ fontFamily: "var(--serif)", fontSize: 17, fontStyle: "italic", color: "var(--ink-2)" }}>“{c.context}”</div>
                </div>
              )}
              <div className="summary-top">
                <div>
                  <div className={`stamp c-${s.band}`}><div className="label">Overall finding</div><div className="h">{s.headline}</div></div>
                  <p className="sub">{s.subline}</p>
                  <div className="small">{s.confidence_text}{s.driven_by && <> The result rests mainly on <b>{s.driven_by}</b>.</>}</div>
                </div>
                <Scale score={r.fusion.overall.score} interval={r.fusion.overall.interval} />
              </div>
              <div className="cols">
                <div>
                  <h3>What we found</h3>
                  {s.found.length === 0 ? <div className="muted">No significant problems.</div> : (
                    <ol className="found">
                      {s.found.map((x) => (
                        <li key={x.finding_id}>
                          <div>{x.text}
                            <div className="meta"><span>{x.file}</span><span className={`tag ${x.strength.toLowerCase()}`}>{x.strength}</span>
                              <button className="linkbtn" onClick={() => goFinding(x.finding_id)}>show me</button></div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                  {s.minor_count > 0 && <div className="small muted" style={{ marginTop: 8 }}>Plus {s.minor_count} weaker observation{s.minor_count > 1 ? "s" : ""}, listed under each file.</div>}
                </div>
                <div>
                  {s.looked_fine.length > 0 && (
                    <>
                      <h3>What looked normal</h3>
                      <ul className="okl">{s.looked_fine.map((x, i) => <li key={i}>{x.text} <span className="f">· {x.file}</span></li>)}</ul>
                    </>
                  )}
                  <h3 style={{ marginTop: s.looked_fine.length ? 22 : 0 }}>What to do next</h3>
                  <ol className="steps">{s.next_steps.map((x, i) => <li key={i}>{x}</li>)}</ol>
                </div>
              </div>
              {s.not_checked.length > 0 && (
                <details className="more">
                  <summary>What we couldn't check <span className="muted small">{s.not_checked.length} note{s.not_checked.length > 1 ? "s" : ""}</span></summary>
                  <ul className="small" style={{ color: "var(--ink-2)", marginTop: 0 }}>{s.not_checked.map((x, i) => <li key={i} style={{ marginBottom: 4 }}>{x}</li>)}</ul>
                </details>
              )}
              <div className="footnote">{s.caveat}</div>
            </section>

            {/* ---------------- files ---------------- */}
            <div id="files" className="section">
              <div className="section-head"><span className="num">01</span><h2>The files</h2><span className="aside small muted">Flags are marked on each file; open “technical details” for the measurements.</span></div>
              {c.evidence.map((e) => <FileSection key={e.id} c={c} ev={e} hl={hl} onUpdate={load} setZoom={setZoom} />)}
            </div>

            {/* ---------------- connections ---------------- */}
            <div id="connections" className="section">
              <div className="section-head"><span className="num">02</span><h2>How the files connect</h2></div>
              <div className="sheet">
                {s.connections.length === 0 ? (
                  <div className="muted">No links between files were found. Cross-checks work best with a video that has speech, together with its caption.</div>
                ) : s.connections.map((x, i) => (
                  <div className="conn" key={i}>
                    <div className="eff" style={{ color: EFFECT[x.effect]?.[1] }}>{EFFECT[x.effect]?.[0]}</div>
                    <div>{x.text}<div className="small muted">{x.evidence_ids.map((id) => c.evidence.find((e) => e.id === id)?.filename || id).join(" ↔ ")}</div></div>
                  </div>
                ))}
                <div className="footnote">We check whether lips match the voice, whether quotes are really said, whether dates agree, whether a photo comes from a video, and whether separate checks flag the same moment.</div>
              </div>
            </div>

            {/* ---------------- appendix ---------------- */}
            <div id="appendix" className="section">
              <div className="section-head"><span className="num">03</span><h2>Technical appendix</h2></div>
              <div className="sheet">
                <Appendix c={c} r={r} />
              </div>
            </div>

            {/* ---------------- custody ---------------- */}
            <div id="custody" className="section">
              <div className="section-head"><span className="num">04</span><h2>Chain of custody</h2></div>
              <div className="sheet">
                <table className="t">
                  <thead><tr><th>File</th><th>SHA-256 fingerprint</th><th>Integrity</th></tr></thead>
                  <tbody>{c.evidence.map((e) => {
                    const ok = r.integrity.find((i) => i.evidence_id === e.id)?.verified;
                    return <tr key={e.id}><td><span className="mono">{e.id}</span> {e.filename}</td><td className="mono" style={{ wordBreak: "break-all" }}>{e.sha256}</td>
                      <td style={{ color: ok ? "var(--green)" : "var(--red)", fontWeight: 600 }}>{ok ? "Unchanged" : "Changed!"}</td></tr>;
                  })}</tbody>
                </table>
                <div className="block-title">Log</div>
                <table className="t">
                  <tbody>{(c.custody || []).map((h, i) => <tr key={i}><td className="mono small" style={{ whiteSpace: "nowrap" }}>{h.at.replace("T", " ")}</td><td>{h.action.replace(/_/g, " ")}</td><td>{h.detail}</td></tr>)}</tbody>
                </table>
                <div className="footnote">Originals are stored read-only and re-fingerprinted when the report is produced. Every examiner decision is added to this log.</div>
              </div>
            </div>
          </div>
        </div>
      )}
      {zoom && <div className="lightbox" onClick={() => setZoom(null)}><img src={zoom} alt="" /></div>}
    </div>
  );
}

function jump(e, id) {
  e.preventDefault();
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function Appendix({ c, r }) {
  const o = r.fusion.overall;
  return (
    <>
      <div className="kv">
        <div>Fused indicator score</div><div><span className="mono">{o.score.toFixed(3)}</span> (uncertainty band {o.interval[0].toFixed(2)}–{o.interval[1].toFixed(2)})</div>
        <div>Signal agreement</div><div className="mono">{o.agreement != null ? o.agreement.toFixed(2) : "n/a"}</div>
        <div>Evidence weight</div><div className="mono">{o.evidence_weight} from {o.n_signals} signals</div>
        {o.driven_by && <><div>Case score source</div><div>Most suspicious item <span className="mono">{o.driven_by}</span>; pooled across all items {o.pooled_score?.toFixed(3)}</div></>}
        <div>Fusion method</div><div className="small">{r.fusion.method}</div>
        <div>Engine</div><div className="small">TruthLens {r.engine.version} on {r.engine.device}. Models: {Object.values(r.engine.models).join(", ")}; Whisper {r.engine.whisper}</div>
      </div>

      <details className="more">
        <summary>Score by media type and by file</summary>
        <table className="t">
          <thead><tr><th>Group</th><th style={{ width: 160 }}>Score</th><th>Band</th><th>Result</th></tr></thead>
          <tbody>
            {Object.entries(r.fusion.by_modality).map(([m, v]) => (
              <tr key={m}><td><Kind m={m} /></td><td><span className="mono">{v.score.toFixed(2)}</span><Meter value={v.score} /></td><td className="mono">{v.interval[0].toFixed(2)}–{v.interval[1].toFixed(2)}</td><td>{v.band_label}</td></tr>
            ))}
            {Object.entries(r.fusion.by_evidence).map(([id, v]) => (
              <tr key={id}><td><span className="mono">{id}</span> {c.evidence.find((e) => e.id === id)?.filename}</td><td><span className="mono">{v.score.toFixed(2)}</span><Meter value={v.score} /></td><td className="mono">{v.interval[0].toFixed(2)}–{v.interval[1].toFixed(2)}</td><td>{v.band_label}</td></tr>
            ))}
          </tbody>
        </table>
      </details>

      <details className="more">
        <summary>What drove the score</summary>
        <table className="t">
          <thead><tr><th>Signal</th><th>File</th><th>Score</th><th>Weight</th><th>Effect</th></tr></thead>
          <tbody>{o.drivers.map((d) => (
            <tr key={d.signal_id}><td>{d.label}</td><td className="mono">{d.evidence_id || "case"}</td><td className="mono" style={{ color: scoreColor(d.score) }}>{d.score.toFixed(2)}</td><td className="mono">{d.weight}</td>
              <td style={{ color: d.push > 0 ? "var(--red)" : "var(--green)" }}>{d.push > 0 ? "raises" : "lowers"} suspicion</td></tr>
          ))}</tbody>
        </table>
      </details>

      <details className="more">
        <summary>All detector results <span className="muted small">{r.signals.length}</span></summary>
        <table className="t">
          <thead><tr><th>Detector</th><th>File</th><th>Observation</th><th style={{ width: 100 }}>Score</th><th>Reliability</th></tr></thead>
          <tbody>{[...r.signals].sort((a, b) => b.score * b.reliability - a.score * a.reliability).map((x) => (
            <tr key={x.id}><td>{x.label}<div><Kind m={x.modality} /></div></td><td className="mono">{x.evidence_id || "case"}</td><td className="small">{x.explanation}</td>
              <td><span className="mono">{x.score.toFixed(2)}</span><Meter value={x.score} /></td><td className="mono">{x.reliability.toFixed(2)}</td></tr>
          ))}</tbody>
        </table>
      </details>

      <details className="more">
        <summary>All findings with locations <span className="muted small">{r.findings.length}</span></summary>
        <table className="t">
          <thead><tr><th>ID</th><th>Finding</th><th>File</th><th>Score</th><th>Reliability</th></tr></thead>
          <tbody>{r.findings.map((f) => (
            <tr key={f.id}><td className="mono">{f.id}</td><td>{f.title}<div className="small muted">{f.category} · {f.detector}</div></td><td className="mono">{f.evidence_id || "case"}</td>
              <td className="mono">{f.score.toFixed(2)}</td><td className="mono">{f.confidence.toFixed(2)}</td></tr>
          ))}</tbody>
        </table>
      </details>

      <details className="more">
        <summary>Limitations of this analysis</summary>
        <ul className="small" style={{ marginTop: 0 }}>{r.limitations.map((l, i) => <li key={i} style={{ marginBottom: 4 }}>{l}</li>)}</ul>
      </details>

      <details className="more">
        <summary>Analysis log</summary>
        <table className="t"><tbody>{r.history.map((h, i) => <tr key={i}><td className="mono small">{h.at.slice(11)}</td><td>{h.step}</td><td className="small">{h.detail}</td></tr>)}</tbody></table>
      </details>
    </>
  );
}
