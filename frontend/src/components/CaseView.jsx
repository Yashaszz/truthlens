import React, { useEffect, useMemo, useState } from "react";
import { api, BAND, MODALITY_COLOR, fmtTs, scoreColor } from "../api.js";
import { Meter, RangeGauge } from "./Charts.jsx";
import Findings from "./Findings.jsx";
import EvidenceViewer from "./EvidenceViewer.jsx";

const STAGES = [
  ["ingest", "Ingest", "Hash & preserve"],
  ["analyze", "Analyze", "Per-modality detectors"],
  ["correlate", "Correlate", "Cross-modal links"],
  ["review", "Review", "Human examiner"],
  ["report", "Report", "Traceable export"],
];

export function ModChip({ m }) {
  return <span className="chip"><span className="sw" style={{ background: MODALITY_COLOR[m] || "var(--muted)" }} />{m}</span>;
}

export default function CaseView({ caseId, onChange }) {
  const [c, setC] = useState(null);
  const [tab, setTab] = useState("overview");
  const [err, setErr] = useState("");
  const [focus, setFocus] = useState(null); // {evidenceId, t?, findingId?}

  const load = () => api.getCase(caseId).then(setC).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [caseId]);
  useEffect(() => {
    if (!c || c.status === "complete" || c.status === "failed") return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [c?.status]);
  useEffect(() => { if (c?.status === "complete") onChange?.(); }, [c?.status]);

  if (err) return <div className="page"><div className="empty">{err}</div></div>;
  if (!c) return <div className="page"><div className="empty"><span className="spin" /></div></div>;

  const r = c.results;
  const stageIdx = STAGES.findIndex((s) => s[0] === c.progress?.stage);
  const openEvidence = (evidenceId, t = null, findingId = null) => { setFocus({ evidenceId, t, findingId, n: Date.now() }); setTab("evidence"); };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{c.title}</h2>
          <div className="muted small"><span className="mono">{c.id}</span> · Examiner {c.examiner} · opened {c.created_at.replace("T", " ")}</div>
        </div>
        {r && (
          <div style={{ display: "flex", gap: 8 }}>
            <a className="btn" href={`/api/cases/${c.id}/report.html`} target="_blank" rel="noreferrer">Open report</a>
            <a className="btn" href={`/api/cases/${c.id}/report.html?download=true`}>Download HTML</a>
            <a className="btn" href={`/api/cases/${c.id}/report.json`}>JSON</a>
          </div>
        )}
      </div>

      <div className="stepper" style={{ marginBottom: 18 }}>
        {STAGES.map(([k, n, d], i) => (
          <div key={k} className={`step ${c.status === "complete" ? (i <= 3 ? "done" : "") : i < stageIdx ? "done" : i === stageIdx ? "cur" : ""} ${c.status === "complete" && i === 3 ? "cur" : ""}`}>
            <div className="k">{i + 1} · {d}</div>
            <div className="n">{n}</div>
          </div>
        ))}
      </div>

      {c.status !== "complete" && (
        <div className="card">
          {c.status === "failed" ? (
            <>
              <h3 style={{ color: "var(--red)" }}>Analysis failed</h3>
              <div>{c.progress?.message}</div>
              <pre className="mono small" style={{ whiteSpace: "pre-wrap", color: "var(--muted)" }}>{c.error}</pre>
            </>
          ) : (
            <>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}><span className="spin" /> <b>{c.progress?.message}</b></div>
              <div className="progress"><div style={{ width: `${c.progress?.pct || 0}%` }} /></div>
              <div className="muted small" style={{ marginTop: 10 }}>First run downloads the pretrained models (~1.5 GB); later runs are much faster.</div>
            </>
          )}
          <EvidenceTable c={c} />
        </div>
      )}

      {r && (
        <>
          <div className="tabs">
            {[["overview", "Overview"], ["evidence", "Evidence", c.evidence.length], ["findings", "Findings", r.findings.length],
              ["cross", "Cross-modal", r.links.length], ["signals", "All detectors", r.signals.length], ["custody", "Custody & history"]].map(([k, n, cnt]) => (
              <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {n}{cnt != null && <span className="count">{cnt}</span>}
              </button>
            ))}
          </div>
          {tab === "overview" && <Overview c={c} r={r} onFinding={(f) => openEvidence(f.evidence_id, firstTime(f), f.id)} goTab={setTab} />}
          {tab === "evidence" && <EvidenceViewer c={c} focus={focus} />}
          {tab === "findings" && <Findings c={c} onUpdate={load} onLocate={(f) => openEvidence(f.evidence_id, firstTime(f), f.id)} />}
          {tab === "cross" && <CrossModal c={c} r={r} onFinding={(f) => openEvidence(f.evidence_id, firstTime(f), f.id)} />}
          {tab === "signals" && <Signals r={r} />}
          {tab === "custody" && <Custody c={c} r={r} />}
        </>
      )}
    </div>
  );
}

export const firstTime = (f) => {
  const l = f?.location || {};
  if (l.type === "frames") return l.frames?.[0]?.t;
  if (l.type === "segments") return l.segments?.[0]?.start;
  if (l.type === "timestamps") return l.times?.[0];
  if (l.type === "text") return l.closest_segment?.start;
  return null;
};

function EvidenceTable({ c }) {
  return (
    <table className="t" style={{ marginTop: 16 }}>
      <thead><tr><th>ID</th><th>File</th><th>Type</th><th>SHA-256</th></tr></thead>
      <tbody>
        {c.evidence.map((e) => (
          <tr key={e.id}><td className="mono">{e.id}</td><td>{e.filename}</td><td><ModChip m={e.modality} /></td>
            <td className="mono" style={{ wordBreak: "break-all" }}>{e.sha256}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Overview({ c, r, onFinding, goTab }) {
  const o = r.fusion.overall;
  const band = BAND[o.band] || BAND.inconclusive;
  const top = r.findings.slice(0, 5);
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="card">
        <div className="verdict">
          <div style={{ minWidth: 260 }}>
            <div className="muted small">FUSED ASSESSMENT</div>
            <div className="band" style={{ color: band.color }}>{o.band_label}</div>
            <div className="muted small" style={{ marginTop: 4 }}>
              Indicator score <b style={{ color: "var(--text)" }}>{o.score.toFixed(2)}</b> · uncertainty band{" "}
              <b style={{ color: "var(--text)" }}>{o.interval[0].toFixed(2)}–{o.interval[1].toFixed(2)}</b> · signal agreement{" "}
              <b style={{ color: "var(--text)" }}>{o.agreement != null ? `${Math.round(o.agreement * 100)}%` : "n/a"}</b>
            </div>
            {o.driven_by && (
              <div className="small" style={{ marginTop: 2 }}>
                Driven by the most suspicious item <b className="mono">{o.driven_by}</b>
                <span className="muted"> ({c.evidence.find((e) => e.id === o.driven_by)?.filename}); pooled across all items: {o.pooled_score?.toFixed(2)}</span>
              </div>
            )}
            <div className="muted small">{o.n_signals} detector signals · {r.findings.length} flagged findings · {r.links.length} cross-modal links · analysed in {r.duration_s}s</div>
          </div>
          <div style={{ flex: 1, minWidth: 300 }}><RangeGauge score={o.score} interval={o.interval} /></div>
        </div>
        <div className="notice" style={{ marginTop: 12 }}>
          A detection score is an indicator, not a final verdict. Review each finding's evidence, limitations and alternative explanations below.
        </div>
      </div>

      <div className="grid g3">
        <div className="card">
          <h3>By modality</h3>
          {Object.entries(r.fusion.by_modality).map(([m, v]) => (
            <div key={m} style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}><ModChip m={m} />
                <span className="small">{v.score.toFixed(2)} <span className="muted">[{v.interval[0].toFixed(2)}–{v.interval[1].toFixed(2)}]</span></span></div>
              <div style={{ marginTop: 5 }}><Meter value={v.score} /></div>
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Why: main drivers</h3>
          {o.drivers.slice(0, 7).map((d) => (
            <div key={d.signal_id} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 7, fontSize: 13 }}>
              <span style={{ color: d.push > 0 ? "var(--red)" : "var(--green)", width: 14 }}>{d.push > 0 ? "▲" : "▼"}</span>
              <span style={{ flex: 1 }}>{d.label} <span className="muted small">{d.evidence_id}</span></span>
              <span className="mono" style={{ color: scoreColor(d.score) }}>{d.score.toFixed(2)}</span>
            </div>
          ))}
          <div className="muted small">▲ raises suspicion · ▼ lowers it (weighted by detector reliability)</div>
        </div>
        <div className="card">
          <h3>By evidence item</h3>
          {c.evidence.map((e) => {
            const v = r.fusion.by_evidence[e.id];
            return (
              <div key={e.id} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span className="small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><span className="mono">{e.id}</span> {e.filename}</span>
                  <span className="small">{v ? v.score.toFixed(2) : "–"}</span>
                </div>
                {v && <div style={{ marginTop: 5 }}><Meter value={v.score} /></div>}
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid g-main">
        <div className="card">
          <h3>Top findings</h3>
          {top.length === 0 && <div className="muted">No detector exceeded its flagging threshold.</div>}
          {top.map((f) => (
            <div key={f.id} className="finding-head" style={{ padding: "8px 4px", borderBottom: "1px solid var(--line)" }} onClick={() => onFinding(f)}>
              <span className="fid">{f.id}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{f.title}</div>
                <div className="small muted">{f.evidence_id} · <ModChip m={f.modality} /> · {f.category}</div>
              </div>
              <div style={{ width: 90 }}><div className="small" style={{ textAlign: "right" }}>{f.score.toFixed(2)}</div><Meter value={f.score} /></div>
            </div>
          ))}
          {r.findings.length > 5 && <button className="btn sm" style={{ marginTop: 10 }} onClick={() => goTab("findings")}>All {r.findings.length} findings →</button>}
        </div>
        <div className="grid" style={{ alignContent: "start" }}>
          <div className="card">
            <h3>Recommended human checks</h3>
            <ol style={{ margin: 0, paddingLeft: 18 }}>
              {r.recommendations.map((x, i) => (
                <li key={i} style={{ marginBottom: 6 }}>{x.check} <div className="muted small">{x.because}</div></li>
              ))}
            </ol>
          </div>
          <div className="card">
            <h3>Limitations</h3>
            <ul style={{ margin: 0, paddingLeft: 18 }} className="small">
              {r.limitations.map((l, i) => <li key={i} style={{ marginBottom: 4 }}>{l}</li>)}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function CrossModal({ c, r, onFinding }) {
  const byId = useMemo(() => Object.fromEntries(r.findings.map((f) => [f.id, f])), [r]);
  const color = { strengthens: "var(--red)", weakens: "var(--green)", context: "var(--accent)" };
  const conv = r.findings.filter((f) => f.modality === "cross-modal");
  return (
    <div className="grid g-main">
      <div>
        {r.links.length === 0 && <div className="card empty">No cross-modal relationships found. Add more media types (e.g. a video with speech plus its caption) for stronger correlation.</div>}
        {r.links.map((l, i) => (
          <div key={i} className="link" style={{ borderLeftColor: color[l.effect] }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <b>{l.title}</b>
              <span className="chip" style={{ color: color[l.effect] }}>{l.effect}</span>
            </div>
            <div style={{ margin: "6px 0" }}>{l.description}</div>
            <div className="small muted">
              {l.type} · evidence {l.evidence_ids.join(", ")}
              {l.window && <> · {fmtTs(l.window[0])}–{fmtTs(l.window[1])}</>}
            </div>
            {l.finding_ids?.length > 0 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                {l.finding_ids.filter((id) => byId[id]).map((id) => (
                  <button key={id} className="btn sm" onClick={() => onFinding(byId[id])}>{id} · {byId[id].modality}</button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="card" style={{ alignSelf: "start" }}>
        <h3>How correlation works</h3>
        <ul className="small" style={{ paddingLeft: 18, margin: 0, lineHeight: 1.7 }}>
          <li><b>Temporal convergence</b>: flags from independent channels (face, voice, sync) overlapping in time.</li>
          <li><b>Channel pattern</b>: face vs voice vs lip-sync, e.g. real face + synthetic voice ⇒ dubbing.</li>
          <li><b>Lip-sync</b>: mouth-motion × speech-energy cross-correlation with lag estimate.</li>
          <li><b>Claim vs media</b>: caption quotes/dates checked against Whisper transcript and metadata.</li>
          <li><b>Provenance</b>: perceptual hash links stills to video frames.</li>
        </ul>
        <div className="muted small" style={{ marginTop: 10 }}>Corroborated signals receive 1.3× weight in fusion; contradicting channels widen the uncertainty band.</div>
        <div style={{ marginTop: 12 }}>{conv.length} cross-modal finding(s)</div>
      </div>
    </div>
  );
}

function Signals({ r }) {
  return (
    <div className="card" style={{ overflow: "auto" }}>
      <div className="muted small" style={{ marginBottom: 10 }}>{r.fusion.method}</div>
      <table className="t">
        <thead><tr><th>Detector</th><th>Modality</th><th>Evidence</th><th style={{ width: 120 }}>Score</th><th style={{ width: 110 }}>Reliability</th><th>Observation</th><th>Findings</th></tr></thead>
        <tbody>
          {[...r.signals].sort((a, b) => b.score * b.reliability - a.score * a.reliability).map((s) => (
            <tr key={s.id}>
              <td>{s.label}</td><td><ModChip m={s.modality} /></td><td className="mono">{s.evidence_id || "–"}</td>
              <td><div className="small">{s.score.toFixed(2)}</div><Meter value={s.score} /></td>
              <td><div className="small">{s.reliability.toFixed(2)}</div><Meter value={s.reliability} color="var(--accent)" /></td>
              <td>{s.explanation}</td><td className="mono small">{s.finding_ids.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Custody({ c, r }) {
  return (
    <div className="grid g2">
      <div className="card">
        <h3>Evidence integrity</h3>
        <table className="t">
          <thead><tr><th>ID</th><th>File</th><th>SHA-256</th><th>Status</th></tr></thead>
          <tbody>
            {c.evidence.map((e) => {
              const ok = r.integrity.find((i) => i.evidence_id === e.id)?.verified;
              return (
                <tr key={e.id}><td className="mono">{e.id}</td><td>{e.filename}<div className="muted small">{e.size.toLocaleString()} bytes · received {e.received_at}</div></td>
                  <td className="mono" style={{ wordBreak: "break-all", fontSize: 11 }}>{e.sha256}</td>
                  <td style={{ color: ok ? "var(--green)" : "var(--red)" }}>{ok ? "✔ verified" : "✘ mismatch"}</td></tr>
              );
            })}
          </tbody>
        </table>
        <h3 style={{ marginTop: 20 }}>Analysis history</h3>
        <table className="t">
          <tbody>{r.history.map((h, i) => <tr key={i}><td className="mono small">{h.at.slice(11)}</td><td>{h.step}</td><td>{h.detail}</td></tr>)}</tbody>
        </table>
        <div className="muted small" style={{ marginTop: 10 }}>Engine {r.engine.version} · {r.engine.device} · Whisper {r.engine.whisper}</div>
      </div>
      <div className="card">
        <h3>Chain of custody</h3>
        <table className="t">
          <tbody>{(c.custody || []).map((h, i) => <tr key={i}><td className="mono small" style={{ whiteSpace: "nowrap" }}>{h.at.replace("T", " ")}</td><td>{h.action}</td><td>{h.detail}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
