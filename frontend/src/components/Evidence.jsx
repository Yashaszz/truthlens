import React, { useEffect, useRef, useState } from "react";
import { api, fileUrl, fmtTs, Kind, scoreColor } from "../api.jsx";
import { DualSeries, LagCurve, Meter, Timeline } from "./Charts.jsx";

/* ------------------------------------------------------------ helpers */
export const intervalsOf = (f) => {
  const l = f.location || {};
  if (l.type === "frames") return (l.frames || []).map((x) => ({ start: x.t - 0.4, end: x.t + 0.4, score: f.score }));
  if (l.type === "segments") return (l.segments || []).map((s) => ({ start: s.start, end: s.end, score: s.score ?? f.score }));
  if (l.type === "timestamps") return (l.times || []).map((t) => ({ start: t - 0.3, end: t + 0.3, score: f.score }));
  if (l.type === "text" && l.closest_segment?.start != null) return [{ start: l.closest_segment.start, end: l.closest_segment.end, score: f.score }];
  return [];
};
const firstTime = (f) => { const iv = intervalsOf(f); return iv.length ? Math.max(0, iv[0].start) : null; };

export function locText(l) {
  if (!l) return "–";
  switch (l.type) {
    case "regions": return (l.regions || []).map((r) => `${r.label || "region"} at (${r.bbox[0]}, ${r.bbox[1]}), ${r.bbox[2]}×${r.bbox[3]} px`).join("; ");
    case "frames": return "Frames at " + (l.frames || []).slice(0, 8).map((f) => fmtTs(f.t)).join(", ");
    case "segments": return "Segments " + (l.segments || []).slice(0, 8).map((s) => `${fmtTs(s.start)}–${fmtTs(s.end)}`).join(", ");
    case "timestamps": return "At " + (l.times || []).slice(0, 8).map(fmtTs).join(", ");
    case "metadata": return "File metadata: " + (l.fields || []).join(", ");
    case "text": return `Caption text (${l.source})` + (l.closest_segment?.start != null ? `; closest speech at ${fmtTs(l.closest_segment.start)}` : "");
    case "series": return "Across the whole clip";
    default: return "Whole file";
  }
}

function useMedia() {
  const ref = useRef();
  const [t, setT] = useState(0);
  const seek = (x) => {
    const el = ref.current;
    if (!el) return;
    const go = () => { el.currentTime = Math.max(0, x); setT(x); };
    if (el.readyState >= 1) go(); else el.addEventListener("loadedmetadata", go, { once: true });
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  return { ref, t, setT, seek };
}

const REVIEW = [["confirmed", "Confirm"], ["needs-follow-up", "Needs follow-up"], ["dismissed", "Dismiss"]];
const REVIEW_WORD = { confirmed: "Confirmed by examiner", "needs-follow-up": "Follow-up requested", dismissed: "Dismissed by examiner" };

/* ------------------------------------------------------------ one flag */
export function Flag({ c, f, seek, highlight, onUpdate, setZoom }) {
  const [open, setOpen] = useState(!!highlight);
  const [note, setNote] = useState(f.review?.note || "");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (highlight) setOpen(true); }, [highlight]);
  const t = firstTime(f);
  const rev = f.review || {};
  const review = async (status) => {
    setBusy(true);
    try { await api.review(c.id, f.id, { status, note }); await onUpdate(); } finally { setBusy(false); }
  };
  return (
    <div id={`f-${f.id}`} className={`flag ${highlight ? "hl" : ""}`}>
      <div className="say">{f.plain || f.title}</div>
      <div className="meta">
        <span className={`tag ${(f.strength || "weak").toLowerCase()}`}>{f.strength || "Weak"} signal</span>
        <span>{f.reliability_word}</span>
        {t != null && seek && <button className="linkbtn" onClick={() => seek(t)}>▶ play from {fmtTs(t).replace(/\.\d$/, "")}</button>}
        <button className="linkbtn" onClick={() => setOpen(!open)}>{open ? "hide details" : "technical details"}</button>
        {rev.status && rev.status !== "pending" && <span className={`tag ${rev.status === "dismissed" ? "ok" : rev.status === "confirmed" ? "strong" : "weak"}`}>{REVIEW_WORD[rev.status]}</span>}
      </div>
      {open && (
        <div className="tech">
          <div className="kv">
            <div>Finding</div><div><span className="mono">{f.id}</span> · {f.title}</div>
            <div>What was measured</div><div>{f.description}</div>
            <div>Where</div><div>{locText(f.location)}</div>
            <div>Indicator score</div><div style={{ display: "flex", gap: 10, alignItems: "center" }}><span className="mono">{f.score.toFixed(2)}</span><Meter value={f.score} /></div>
            <div>Detector reliability</div><div style={{ display: "flex", gap: 10, alignItems: "center" }}><span className="mono">{f.confidence.toFixed(2)}</span><Meter value={f.confidence} color="var(--blue)" /></div>
            <div>Detector</div><div className="mono">{f.detector}</div>
            {f.limitations && <><div>Limitations</div><div>{f.limitations}</div></>}
            {f.alternatives?.length > 0 && <><div>Innocent explanations</div><div>{f.alternatives.join("; ")}</div></>}
            {f.related?.length > 0 && <><div>Related findings</div><div className="mono">{f.related.join(", ")}</div></>}
          </div>
          {f.artifacts?.length > 0 && (
            <div className="thumbs">{f.artifacts.map((a) => <img key={a} src={fileUrl(c.id, a)} alt="analysis artifact" onClick={() => setZoom(fileUrl(c.id, a))} />)}</div>
          )}
          <div className="review">
            <span className="small muted">Examiner decision:</span>
            {REVIEW.map(([k, n]) => (
              <button key={k} disabled={busy} className={`btn sm ${rev.status === k ? `sel-${k}` : "ghost"}`} onClick={() => review(k)}>{n}</button>
            ))}
            <input className="in" style={{ flex: 1, minWidth: 180, padding: "5px 9px", fontSize: 13 }} placeholder="Add a note (saved to the custody log)"
              value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
      )}
    </div>
  );
}

function FlagList({ c, findings, seek, hl, onUpdate, setZoom }) {
  const main = findings.filter((f) => f.score >= 0.5 && f.confidence >= 0.3);
  const weak = findings.filter((f) => !main.includes(f));
  const [showWeak, setShowWeak] = useState(weak.some((f) => f.id === hl));
  return (
    <div>
      <div className="label" style={{ marginBottom: 10 }}>What we noticed in this file</div>
      {main.length === 0 && <div className="muted">Nothing significant.</div>}
      {main.map((f) => <Flag key={f.id} c={c} f={f} seek={seek} highlight={hl === f.id} onUpdate={onUpdate} setZoom={setZoom} />)}
      {weak.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button className="linkbtn small" onClick={() => setShowWeak(!showWeak)}>
            {showWeak ? "Hide" : "Show"} {weak.length} weaker observation{weak.length > 1 ? "s" : ""}
          </button>
          {showWeak && <div style={{ marginTop: 10 }}>{weak.map((f) => <Flag key={f.id} c={c} f={f} seek={seek} highlight={hl === f.id} onUpdate={onUpdate} setZoom={setZoom} />)}</div>}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ media pieces */
function Transcript({ tr, flagged, t, onSeek }) {
  if (!tr || !tr.segments?.length) return <div className="muted small">No speech was recognised.</div>;
  const inFlag = (w) => flagged.some((s) => w.start < s.end && w.end > s.start);
  return (
    <>
      <div className="transcript">
        {tr.segments.map((sg, i) => (
          <span key={i}>
            <span className="ts" onClick={() => onSeek(sg.start)}>{fmtTs(sg.start).replace(/\.\d$/, "")}</span>
            {sg.words.length ? sg.words.map((w, k) => (
              <span key={k} className={`w ${inFlag(w) ? "flag" : ""} ${t >= w.start && t < w.end ? "now" : ""} ${w.p < 0.5 ? "lowp" : ""}`}
                onClick={() => onSeek(w.start)}>{w.w} </span>
            )) : sg.text}
            <br />
          </span>
        ))}
      </div>
      <div className="caption">Transcribed automatically ({tr.language}, {tr.model}). Click any word to jump there. Highlighted words fall in flagged audio; dotted words were hard to hear.</div>
    </>
  );
}

function Spectrogram({ src, duration, segments, t, onSeek }) {
  return (
    <div className="spectro" onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * duration); }}>
      <img src={src} alt="sound spectrogram" />
      {segments.map((sg, i) => (
        <div key={i} className="seg" title={`${fmtTs(sg.start)}–${fmtTs(sg.end)}`}
          style={{ left: `${(Math.max(0, sg.start) / duration) * 100}%`, width: `${Math.max(0.5, ((sg.end - sg.start) / duration) * 100)}%` }} />
      ))}
      <div className="cursor" style={{ left: `${(t / duration) * 100}%` }} />
    </div>
  );
}

function audioLanes(a, findings) {
  const lanes = [];
  const voiceFlags = findings.filter((f) => f.detector === "audio_spoof_model").flatMap(intervalsOf);
  if (voiceFlags.length) lanes.push({ name: "Synthetic voice", color: "var(--c-audio)", kind: "segments", items: voiceFlags });
  const splice = findings.filter((f) => ["digital_silence", "noise_floor_jumps"].includes(f.detector)).flatMap(intervalsOf);
  if (splice.length) lanes.push({ name: "Possible edits", color: "var(--orange)", kind: "segments", items: splice });
  if (a?.transcript?.segments?.length)
    lanes.push({ name: "Speech", color: "var(--muted)", kind: "segments", items: a.transcript.segments.map((s) => ({ start: s.start, end: s.end, score: 0.15, label: s.text })) });
  return lanes;
}

function SignalTable({ signals }) {
  if (!signals.length) return null;
  return (
    <table className="t">
      <thead><tr><th>Check</th><th>Result</th><th style={{ width: 110 }}>Score</th><th style={{ width: 90 }}>Reliability</th></tr></thead>
      <tbody>
        {[...signals].sort((a, b) => b.score - a.score).map((x) => (
          <tr key={x.id}><td>{x.label}</td><td className="small">{x.explanation}</td>
            <td><span className="mono" style={{ color: scoreColor(x.score) }}>{x.score.toFixed(2)}</span><Meter value={x.score} /></td>
            <td className="mono">{x.reliability.toFixed(2)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Metadata({ ev, s }) {
  const rows = [["SHA-256", ev.sha256], ["Size", `${ev.size.toLocaleString()} bytes`], ["Received", ev.received_at.replace("T", " ")], ["Stored as", `${ev.stored_as} (read-only)`]];
  const push = (k, v) => v != null && v !== "" && rows.push([k, typeof v === "object" ? JSON.stringify(v) : String(v)]);
  push("Format", s.format && `${s.format} ${s.width}×${s.height}`);
  push("Camera", s.camera); push("Taken", s.capture_time); push("Modified", s.modify_time);
  push("GPS", s.gps && `${s.gps.lat}, ${s.gps.lon}`);
  if (s.probe) {
    push("Duration", s.duration && `${s.duration} s at ${s.fps} fps`);
    push("Video stream", s.probe.video); push("Audio stream", s.probe.audio);
    Object.entries(s.probe.tags || {}).forEach(([k, v]) => push(k, v));
  }
  if (s.bandwidth) push("Bandwidth", `${s.bandwidth.effective_cutoff_hz} Hz cutoff at ${s.bandwidth.sample_rate} Hz`);
  if (s.prosody) push("Voice pitch", `median ${s.prosody.f0_median} Hz, range ${s.prosody.range_semitones} semitones`);
  Object.entries(s.exif || {}).slice(0, 30).forEach(([k, v]) => !["Make", "Model"].includes(k) && push(`EXIF ${k}`, v));
  return (
    <table className="t"><tbody>{rows.map(([k, v]) => <tr key={k}><td className="muted" style={{ width: 150 }}>{k}</td><td className="mono" style={{ wordBreak: "break-all" }}>{v}</td></tr>)}</tbody></table>
  );
}

/* ------------------------------------------------------------ viewers */
function ImageViewer({ c, ev, s, findings }) {
  const a = s.artifacts || {};
  const layers = [["original", "Original", fileUrl(c.id, ev.stored_as), `${s.width}×${s.height} ${s.format}. Boxes mark the flagged areas.`]];
  if (a.ela) layers.push(["ela", "Compression map", fileUrl(c.id, a.ela), "Error level analysis: bright areas re-compress differently. Boxes are areas still unusual after allowing for detail and texture."]);
  if (a.noise) layers.push(["noise", "Camera-grain map", fileUrl(c.id, a.noise), "Bright blocks have a noise level that doesn't match the rest of the picture."]);
  if (a.copy_move) layers.push(["copy", "Copied areas", fileUrl(c.id, a.copy_move), "Green box: original area. Red box: its copy. Yellow lines join matching points."]);
  const [layer, setLayer] = useState("original");
  const cur = layers.find((l) => l[0] === layer) || layers[0];
  const boxes = findings.filter((f) => f.location?.type === "regions" && f.location.width && f.score >= 0.5);
  return (
    <div>
      {layers.length > 1 && <div className="layers">{layers.map(([k, n]) => <button key={k} className={layer === k ? "on" : ""} onClick={() => setLayer(k)}>{n}</button>)}</div>}
      <div className="viewer">
        <img src={cur[2]} alt={cur[1]} />
        {layer === "original" && boxes.flatMap((f) => f.location.regions.slice(0, 3).map((rg, i) => (
          <div key={f.id + i} className="box" style={{
            left: `${(rg.bbox[0] / f.location.width) * 100}%`, top: `${(rg.bbox[1] / f.location.height) * 100}%`,
            width: `${(rg.bbox[2] / f.location.width) * 100}%`, height: `${(rg.bbox[3] / f.location.height) * 100}%`,
          }}><span>{f.id}{rg.label && !/^[RN]\d$/.test(rg.label) ? ` ${rg.label}` : ""}</span></div>
        )))}
      </div>
      <div className="caption">{cur[3]}</div>
    </div>
  );
}

/* ------------------------------------------------------------ a whole file */
export function FileSection({ c, ev, hl, onUpdate, setZoom }) {
  const r = c.results;
  const s = r.evidence_summaries[ev.id] || {};
  const say = c.summary?.per_evidence?.[ev.id];
  const findings = r.findings.filter((f) => f.evidence_id === ev.id).sort((a, b) => b.score * b.confidence - a.score * a.confidence);
  const signals = r.signals.filter((x) => x.evidence_id === ev.id);
  const media = useMedia();
  const isAV = ev.modality === "video" || ev.modality === "audio";
  const a = ev.modality === "video" ? s.audio || {} : s;
  const dur = s.duration || a.duration || 1;
  const audioFlags = findings.filter((f) => ["audio_spoof_model", "digital_silence", "noise_floor_jumps"].includes(f.detector)).flatMap(intervalsOf);

  let lanes = [];
  if (ev.modality === "video") {
    if (s.frame_timeline?.some((x) => x.p_fake != null))
      lanes.push({ name: "Face altered?", color: "var(--c-video)", kind: "series", items: s.frame_timeline.filter((x) => x.p_fake != null).map((x) => ({ t: x.t, v: x.p_fake })) });
    lanes.push(...audioLanes(a, findings));
    if (s.sync?.windows?.length) {
      const bad = s.sync.windows.filter((w) => w.corr < 0.1);
      if (bad.length) lanes.push({ name: "Lip-sync off", color: "var(--c-cross)", kind: "segments", items: bad.map((w) => ({ ...w, score: Math.min(1, 0.5 - w.corr) })) });
    }
    if (s.cuts?.length) lanes.push({ name: "Hard cuts", color: "var(--amber)", kind: "points", items: s.cuts });
    if (s.frozen?.length) lanes.push({ name: "Frozen picture", color: "var(--amber)", kind: "segments", items: s.frozen });
    const conv = findings.filter((f) => f.detector === "cross_modal").flatMap(intervalsOf);
    if (conv.length) lanes.push({ name: "Checks agree", color: "var(--red)", kind: "segments", items: conv });
  } else if (ev.modality === "audio") {
    lanes = audioLanes(s, findings);
  }
  const flaggedFrames = findings.filter((f) => f.detector === "face_deepfake_model" && f.location?.type === "frames").flatMap((f) => f.location.frames).filter((x) => x.thumb);

  return (
    <section id={`file-${ev.id}`} className="sheet file-sec">
      <div className="file-head">
        <div style={{ flex: 1, minWidth: 260 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 4 }}>
            <Kind m={ev.modality} /><span className="mono muted">{ev.id}</span>
            {say && <span className={`tag b-${say.band}`}>{say.verdict}</span>}
          </div>
          <h3>{ev.filename}</h3>
          {say && <div className="say">{say.sentence}</div>}
        </div>
      </div>
      {s.error && <div className="notice" style={{ marginBottom: 12 }}>This file could not be fully analysed: {s.error}</div>}

      <div className="file-grid">
        <div>
          {ev.modality === "image" && <ImageViewer c={c} ev={ev} s={s} findings={findings} />}
          {ev.modality === "video" && (
            <>
              <div className="viewer" style={{ display: "block" }}>
                <video ref={media.ref} src={fileUrl(c.id, s.preview || ev.stored_as)} controls onTimeUpdate={(e) => media.setT(e.target.currentTime)} />
              </div>
              <div className="caption">{s.duration} s · {s.fps} fps · {s.samples} frames sampled, {s.face_frames} with a visible face</div>
              {flaggedFrames.length > 0 && (
                <div className="thumbs">{flaggedFrames.map((x) => (
                  <div key={x.frame} className="tiny mono" style={{ textAlign: "center" }}>
                    <img src={fileUrl(c.id, x.thumb)} alt={`frame at ${x.t}s`} onClick={() => media.seek(x.t)} style={{ cursor: "pointer" }} /><br />{fmtTs(x.t)}
                  </div>
                ))}</div>
              )}
            </>
          )}
          {ev.modality === "audio" && (
            <>
              <audio className="audio-el" ref={media.ref} src={fileUrl(c.id, s.preview || ev.stored_as)} controls onTimeUpdate={(e) => media.setT(e.target.currentTime)} />
              {s.artifacts?.spectrogram && <Spectrogram src={fileUrl(c.id, s.artifacts.spectrogram)} duration={dur} segments={audioFlags} t={media.t} onSeek={media.seek} />}
              <div className="caption">Sound picture (spectrogram): time runs left to right, pitch bottom to top. White-framed bands are flagged; click to listen.</div>
            </>
          )}
          {ev.modality === "text" && <pre className="transcript" style={{ whiteSpace: "pre-wrap", fontFamily: "var(--sans)", fontSize: 14 }}>{s.preview}</pre>}
        </div>
        <FlagList c={c} findings={findings} seek={isAV ? media.seek : null} hl={hl} onUpdate={onUpdate} setZoom={setZoom} />
      </div>

      {isAV && lanes.length > 0 && (
        <>
          <div className="block-title">Timeline <span className="muted small" style={{ fontFamily: "var(--sans)", fontWeight: 400 }}>· click anywhere to jump</span></div>
          <Timeline duration={dur} lanes={lanes} current={media.t} onSeek={media.seek} />
        </>
      )}
      {isAV && a.transcript && (
        <>
          <div className="block-title">What is said</div>
          <Transcript tr={a.transcript} flagged={audioFlags} t={media.t} onSeek={media.seek} />
        </>
      )}

      <details className="more">
        <summary>Technical data for this file <span className="muted small">{signals.length} checks, metadata, fingerprint</span></summary>
        <div style={{ display: "grid", gap: 22, paddingBottom: 8 }}>
          {ev.modality === "video" && s.sync && (
            <div>
              <div className="block-title" style={{ marginTop: 0 }}>Lip-sync analysis</div>
              {!s.sync.assessable ? <div className="muted small">Not possible: {s.sync.reason || "not enough on-screen speech"} ({s.sync.valid_seconds} s usable).</div> : (
                <>
                  <div className="small">Mouth movement vs. voice loudness: best match r = <b>{s.sync.best_corr}</b> at <b>{(s.sync.best_lag_s * 1000).toFixed(0)} ms</b> offset (r = {s.sync.zero_lag_corr} with no offset), over {s.sync.valid_seconds} s of on-screen speech.</div>
                  <div className="tiny" style={{ marginTop: 6 }}><span style={{ color: "var(--c-video)" }}>■ mouth movement</span> &nbsp; <span style={{ color: "var(--c-audio)" }}>■ voice loudness</span></div>
                  <DualSeries series={s.sync.series} />
                  <LagCurve curve={s.sync.lag_curve} best={s.sync.best_lag_s} />
                </>
              )}
            </div>
          )}
          {ev.modality === "video" && a.artifacts?.spectrogram && (
            <div><div className="block-title" style={{ marginTop: 0 }}>Soundtrack spectrogram</div>
              <Spectrogram src={fileUrl(c.id, a.artifacts.spectrogram)} duration={a.duration || dur} segments={audioFlags} t={media.t} onSeek={media.seek} /></div>
          )}
          {ev.modality === "video" && s.artifacts?.keyframe_ela && (
            <div><div className="block-title" style={{ marginTop: 0 }}>Compression map of the key frame at {fmtTs(s.keyframe_t)}</div>
              <img src={fileUrl(c.id, s.artifacts.keyframe_ela)} alt="key frame ELA" style={{ maxWidth: "100%", maxHeight: 320, border: "1px solid var(--rule)" }} /></div>
          )}
          {ev.modality === "audio" && s.curves && (
            <div><div className="block-title" style={{ marginTop: 0 }}>Acoustic features (MFCC, zero-crossing rate, energy)</div>
              <Timeline duration={dur} current={media.t} onSeek={media.seek} lanes={["rms_db", "zcr", "flatness", "mfcc_delta"].map((k, i) => {
                const arr = s.curves[k]; const mn = Math.min(...arr), mx = Math.max(...arr);
                return { name: ["Energy (dB)", "Zero-crossing rate", "Spectral flatness", "MFCC change"][i], color: ["var(--blue)", "var(--c-text)", "var(--c-image)", "var(--c-audio)"][i], kind: "series",
                  items: arr.map((v, j) => ({ t: j * s.curves.t_step, v: (v - mn) / (mx - mn || 1) })) };
              })} />
              {s.window_scores?.length > 0 && <div className="caption">Voice classifier per 4 s window: {s.window_scores.map((w) => `${fmtTs(w.start).replace(/\.\d$/, "")} → ${w.p_fake.toFixed(2)}`).join(" · ")}</div>}
            </div>
          )}
          <div><div className="block-title" style={{ marginTop: 0 }}>Every check run on this file</div><SignalTable signals={signals} /></div>
          <div><div className="block-title" style={{ marginTop: 0 }}>Metadata and fingerprint</div><Metadata ev={ev} s={s} /></div>
        </div>
      </details>
    </section>
  );
}
