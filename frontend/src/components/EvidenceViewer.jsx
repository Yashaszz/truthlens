import React, { useEffect, useMemo, useRef, useState } from "react";
import { fileUrl, fmtTs, scoreColor } from "../api.js";
import { DualSeries, LagCurve, Meter, Timeline } from "./Charts.jsx";
import { ModChip } from "./CaseView.jsx";

const intervalsOf = (f) => {
  const l = f.location || {};
  if (l.type === "frames") return (l.frames || []).map((x) => ({ start: x.t - 0.4, end: x.t + 0.4, score: f.score }));
  if (l.type === "segments") return (l.segments || []).map((s) => ({ start: s.start, end: s.end, score: s.score ?? f.score }));
  if (l.type === "timestamps") return (l.times || []).map((t) => ({ start: t - 0.3, end: t + 0.3, score: f.score }));
  return [];
};

export default function EvidenceViewer({ c, focus }) {
  const r = c.results;
  const [sel, setSel] = useState(focus?.evidenceId || c.evidence[0]?.id);
  useEffect(() => { if (focus?.evidenceId) setSel(focus.evidenceId); }, [focus?.n]);
  const ev = c.evidence.find((e) => e.id === sel) || c.evidence[0];
  const s = r.evidence_summaries[ev.id] || {};
  const findings = r.findings.filter((f) => f.evidence_id === ev.id);
  const signals = r.signals.filter((x) => x.evidence_id === ev.id);
  const seekTo = focus?.evidenceId === ev.id ? focus : null;

  return (
    <div>
      <div className="seg-toggle">
        {c.evidence.map((e) => (
          <button key={e.id} className={e.id === ev.id ? "on" : ""} onClick={() => setSel(e.id)}>
            <span className="mono">{e.id}</span> · {e.filename.length > 28 ? e.filename.slice(0, 26) + "…" : e.filename}
          </button>
        ))}
      </div>
      {s.error && <div className="notice" style={{ marginBottom: 12 }}>Analysis error: {s.error}</div>}
      {ev.modality === "image" && <ImageView c={c} ev={ev} s={s} findings={findings} focus={seekTo} />}
      {ev.modality === "video" && <VideoView c={c} ev={ev} s={s} findings={findings} focus={seekTo} />}
      {ev.modality === "audio" && <AudioView c={c} ev={ev} s={s} findings={findings} focus={seekTo} />}
      {ev.modality === "text" && (
        <div className="card"><h3>Text evidence</h3><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{s.preview}</pre></div>
      )}
      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Detector results for {ev.id}</h3>
          <table className="t"><tbody>
            {signals.map((x) => (
              <tr key={x.id}><td>{x.label}<div className="muted small">{x.explanation}</div></td>
                <td style={{ width: 110 }}><div className="small" style={{ color: scoreColor(x.score) }}>{x.score.toFixed(2)}</div><Meter value={x.score} /></td>
                <td style={{ width: 80 }} className="small muted">rel {x.reliability.toFixed(2)}</td></tr>
            ))}
            {signals.length === 0 && <tr><td className="muted">No detector signals.</td></tr>}
          </tbody></table>
        </div>
        <div className="card">
          <h3>Source trace</h3>
          <div className="kv" style={{ marginTop: 0 }}>
            <div>File</div><div>{ev.filename}</div>
            <div>Type</div><div><ModChip m={ev.modality} /></div>
            <div>Size</div><div>{ev.size.toLocaleString()} bytes</div>
            <div>SHA-256</div><div className="mono" style={{ wordBreak: "break-all" }}>{ev.sha256}</div>
            <div>Received</div><div>{ev.received_at.replace("T", " ")}</div>
            <div>Stored as</div><div className="mono">{ev.stored_as} (read-only)</div>
          </div>
          <Metadata s={s} />
        </div>
      </div>
    </div>
  );
}

function Metadata({ s }) {
  const rows = [];
  const push = (k, v) => v != null && v !== "" && rows.push([k, typeof v === "object" ? JSON.stringify(v) : String(v)]);
  push("Format", s.format && `${s.format} ${s.width}×${s.height}`);
  push("Camera", s.camera);
  push("Capture time", s.capture_time);
  push("Modify time", s.modify_time);
  push("GPS", s.gps && `${s.gps.lat}, ${s.gps.lon}`);
  push("C2PA manifest", s.c2pa_manifest ? "present" : null);
  if (s.probe) {
    push("Duration", s.duration && `${s.duration}s @ ${s.fps} fps`);
    push("Video stream", s.probe.video);
    push("Audio stream", s.probe.audio);
    Object.entries(s.probe.tags || {}).forEach(([k, v]) => push(k, v));
  }
  if (s.bandwidth) push("Bandwidth", `${s.bandwidth.effective_cutoff_hz} Hz cutoff @ ${s.bandwidth.sample_rate} Hz`);
  if (s.prosody) push("Prosody", `F0 ${s.prosody.f0_median} Hz, range ${s.prosody.range_semitones} st`);
  Object.entries(s.exif || {}).slice(0, 30).forEach(([k, v]) => !["Make", "Model"].includes(k) && push(`EXIF ${k}`, v));
  if (!rows.length) return null;
  return (
    <>
      <h3 style={{ marginTop: 18 }}>Metadata</h3>
      <table className="t"><tbody>{rows.map(([k, v]) => <tr key={k}><td className="muted" style={{ width: 160 }}>{k}</td><td className="mono" style={{ wordBreak: "break-all" }}>{v}</td></tr>)}</tbody></table>
    </>
  );
}

/* ------------------------------------------------------------------ image */
function ImageView({ c, ev, s, findings }) {
  const layers = [["original", "Original", fileUrl(c.id, ev.stored_as)]];
  const a = s.artifacts || {};
  if (a.ela) layers.push(["ela", "Error level (ELA)", fileUrl(c.id, a.ela)]);
  if (a.noise) layers.push(["noise", "Noise residual", fileUrl(c.id, a.noise)]);
  if (a.copy_move) layers.push(["copy_move", "Copy-move", fileUrl(c.id, a.copy_move)]);
  const [layer, setLayer] = useState("original");
  const [boxes, setBoxes] = useState(true);
  const cur = layers.find((l) => l[0] === layer) || layers[0];
  const regionFindings = findings.filter((f) => f.location?.type === "regions" && f.location.width);
  return (
    <div className="grid g-main">
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <div className="seg-toggle">{layers.map(([k, n]) => <button key={k} className={layer === k ? "on" : ""} onClick={() => setLayer(k)}>{n}</button>)}</div>
          <label className="small muted"><input type="checkbox" checked={boxes} onChange={(e) => setBoxes(e.target.checked)} /> flagged regions</label>
        </div>
        <div className="viewer">
          <img src={cur[2]} alt={cur[1]} />
          {boxes && layer === "original" && regionFindings.flatMap((f) => f.location.regions.map((rg, i) => (
            <div key={f.id + i} className="box" style={{
              left: `${(rg.bbox[0] / f.location.width) * 100}%`, top: `${(rg.bbox[1] / f.location.height) * 100}%`,
              width: `${(rg.bbox[2] / f.location.width) * 100}%`, height: `${(rg.bbox[3] / f.location.height) * 100}%`,
              borderColor: scoreColor(f.score),
            }}><span style={{ background: scoreColor(f.score) }}>{f.id} {rg.label}</span></div>
          )))}
        </div>
        <div className="muted small" style={{ marginTop: 8 }}>
          {layer === "ela" && "Bright areas recompress differently. Boxes mark regions that stay anomalous after correcting for texture."}
          {layer === "noise" && "Highlights blocks whose sensor-noise level departs from the rest of the image."}
          {layer === "copy_move" && "Green = source, red = duplicate; yellow lines connect matching keypoints."}
          {layer === "original" && `${s.width}×${s.height} ${s.format} · ${s.faces?.length || 0} face(s) detected`}
        </div>
      </div>
      <FindingList findings={findings} />
    </div>
  );
}

function FindingList({ findings, onSeek }) {
  return (
    <div className="card" style={{ alignSelf: "start" }}>
      <h3>Findings on this item</h3>
      {findings.length === 0 && <div className="muted">None flagged.</div>}
      {findings.map((f) => {
        const iv = intervalsOf(f);
        return (
          <div key={f.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)", cursor: onSeek && iv.length ? "pointer" : "default" }}
            onClick={() => onSeek && iv.length && onSeek(Math.max(0, iv[0].start))}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="fid">{f.id}</span><b style={{ flex: 1, fontSize: 13 }}>{f.title}</b>
              <span className="mono" style={{ color: scoreColor(f.score) }}>{f.score.toFixed(2)}</span>
            </div>
            <div className="small muted" style={{ marginTop: 3 }}>{f.description.slice(0, 180)}{f.description.length > 180 ? "…" : ""}</div>
            {onSeek && iv.length > 0 && <div className="small" style={{ color: "var(--accent)" }}>▶ {fmtTs(Math.max(0, iv[0].start))}</div>}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------ media helpers */
function useMedia(focus) {
  const ref = useRef();
  const [t, setT] = useState(0);
  const seek = (x) => { if (ref.current) { ref.current.currentTime = Math.max(0, x); setT(x); } };
  useEffect(() => {
    if (focus?.t == null || !ref.current) return;
    const el = ref.current;
    const go = () => { el.currentTime = Math.max(0, focus.t); setT(focus.t); };
    if (el.readyState >= 1) go(); else el.addEventListener("loadedmetadata", go, { once: true });
  }, [focus?.n]);
  return { ref, t, setT, seek };
}

function Transcript({ tr, flagged, t, onSeek }) {
  if (!tr) return <div className="muted small">No transcript (no speech recognised or Whisper unavailable).</div>;
  const inFlag = (w) => flagged.some((s) => w.start < s.end && w.end > s.start);
  return (
    <>
      <div className="muted small" style={{ marginBottom: 6 }}>Language: {tr.language} ({Math.round(tr.language_probability * 100)}%) · {tr.model} · click a word to seek · dotted = low ASR confidence</div>
      <div className="transcript">
        {tr.segments.map((sg, i) => (
          <span key={i}>
            <span className="muted mono small" style={{ cursor: "pointer" }} onClick={() => onSeek(sg.start)}>[{fmtTs(sg.start)}] </span>
            {sg.words.length ? sg.words.map((w, k) => (
              <span key={k} className={`w ${inFlag(w) ? "flag" : ""} ${t >= w.start && t < w.end ? "now" : ""} ${w.p < 0.5 ? "lowp" : ""}`}
                onClick={() => onSeek(w.start)}>{w.w} </span>
            )) : sg.text}
            <br />
          </span>
        ))}
      </div>
    </>
  );
}

function Spectrogram({ src, duration, segments, t, onSeek }) {
  return (
    <div className="spectro" onClick={(e) => {
      const r = e.currentTarget.getBoundingClientRect();
      onSeek(((e.clientX - r.left) / r.width) * duration);
    }} style={{ cursor: "pointer" }}>
      <img src={src} alt="mel spectrogram" />
      {segments.map((sg, i) => (
        <div key={i} className="seg" title={`${fmtTs(sg.start)}–${fmtTs(sg.end)}`}
          style={{ left: `${(sg.start / duration) * 100}%`, width: `${Math.max(0.4, ((sg.end - sg.start) / duration) * 100)}%` }} />
      ))}
      <div className="cursor" style={{ left: `${(t / duration) * 100}%` }} />
    </div>
  );
}

function audioLanes(a, findings, prefix = "") {
  const lanes = [];
  if (a?.window_scores?.length)
    lanes.push({ name: `${prefix}Voice P(fake)`, color: "var(--c-audio)", kind: "series",
      items: a.window_scores.map((w) => ({ t: (w.start + w.end) / 2, v: w.p_fake })) });
  if (a?.transcript?.segments?.length)
    lanes.push({ name: "Speech (Whisper)", color: "var(--muted)", kind: "segments",
      items: a.transcript.segments.map((s) => ({ start: s.start, end: s.end, score: 0.2, label: s.text })) });
  const splice = findings.filter((f) => ["digital_silence", "noise_floor_jumps"].includes(f.detector)).flatMap(intervalsOf);
  if (splice.length) lanes.push({ name: "Splice indicators", color: "var(--orange)", kind: "segments", items: splice });
  return lanes;
}

/* ------------------------------------------------------------------ video */
function VideoView({ c, ev, s, findings, focus }) {
  const { ref, t, setT, seek } = useMedia(focus);
  const dur = s.duration || 1;
  const a = s.audio || {};
  const sync = s.sync;
  const lanes = [];
  if (s.frame_timeline?.some((x) => x.p_fake != null))
    lanes.push({ name: "Face P(deepfake)", color: "var(--c-video)", kind: "series",
      items: s.frame_timeline.filter((x) => x.p_fake != null).map((x) => ({ t: x.t, v: x.p_fake })) });
  lanes.push(...audioLanes(a, findings));
  if (sync?.windows?.length)
    lanes.push({ name: "Lip-sync breaks", color: "var(--c-cross)", kind: "segments",
      items: sync.windows.filter((w) => w.corr < 0.1).map((w) => ({ start: w.start, end: w.end, score: Math.min(1, 0.5 - w.corr), label: `r=${w.corr}` })) });
  if (s.cuts?.length) lanes.push({ name: "Scene cuts", color: "var(--amber)", kind: "points", items: s.cuts.map((x) => ({ t: x.t })) });
  if (s.frozen?.length) lanes.push({ name: "Frozen frames", color: "var(--amber)", kind: "segments", items: s.frozen });
  const conv = findings.filter((f) => f.detector === "cross_modal").flatMap(intervalsOf);
  if (conv.length) lanes.push({ name: "Convergence", color: "var(--red)", kind: "segments", items: conv });
  const flaggedFrames = findings.filter((f) => f.detector === "face_deepfake_model" && f.location?.type === "frames").flatMap((f) => f.location.frames);
  const audioFlag = findings.filter((f) => f.detector === "audio_spoof_model").flatMap(intervalsOf);
  const src = s.preview ? fileUrl(c.id, s.preview) : fileUrl(c.id, ev.stored_as);
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid g-main">
        <div className="card">
          <div className="viewer" style={{ display: "block" }}>
            <video ref={ref} src={src} controls onTimeUpdate={(e) => setT(e.target.currentTime)} style={{ width: "100%" }} />
          </div>
          <div className="muted small" style={{ marginTop: 6 }}>
            {s.duration}s · {s.fps} fps · {s.frames} frames read · {s.samples} sampled · {s.face_frames} with faces
          </div>
          {flaggedFrames.length > 0 && (
            <div className="thumbs">
              {flaggedFrames.filter((f) => f.thumb).map((f) => (
                <div key={f.frame} style={{ textAlign: "center" }}>
                  <img src={fileUrl(c.id, f.thumb)} alt={`frame ${f.frame}`} onClick={() => seek(f.t)} style={{ cursor: "pointer" }} />
                  <div className="small mono">{fmtTs(f.t)} · {f.score.toFixed(2)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
        <FindingList findings={findings} onSeek={seek} />
      </div>
      <div className="card">
        <h3>Cross-modal timeline · click to seek</h3>
        <Timeline duration={dur} lanes={lanes} current={t} onSeek={seek} />
      </div>
      <div className="grid g2">
        <div className="card">
          <h3>Audio-visual sync</h3>
          {!sync && <div className="muted">No audio track.</div>}
          {sync && !sync.assessable && <div className="muted">Not assessable: {sync.reason || "insufficient on-screen speech"} ({sync.valid_seconds}s usable).</div>}
          {sync?.assessable && (
            <>
              <div className="small" style={{ marginBottom: 8 }}>
                Peak correlation <b>{sync.best_corr}</b> at <b>{(sync.best_lag_s * 1000).toFixed(0)} ms</b> · zero-lag r = {sync.zero_lag_corr} · {sync.valid_seconds}s of on-screen speech
              </div>
              <div className="small"><span style={{ color: "var(--c-video)" }}>■ mouth motion</span> &nbsp; <span style={{ color: "var(--c-audio)" }}>■ speech energy</span></div>
              <DualSeries series={sync.series} />
              <div className="muted small" style={{ margin: "8px 0 2px" }}>Correlation vs audio lag (peak near 0 ms = in sync)</div>
              <LagCurve curve={sync.lag_curve} best={sync.best_lag_s} />
            </>
          )}
        </div>
        <div className="card">
          <h3>Transcript (Whisper)</h3>
          <Transcript tr={a.transcript} flagged={audioFlag} t={t} onSeek={seek} />
        </div>
      </div>
      {a.artifacts?.spectrogram && (
        <div className="card">
          <h3>Audio track spectrogram · red = voice-spoof flagged</h3>
          <Spectrogram src={fileUrl(c.id, a.artifacts.spectrogram)} duration={a.duration || dur} segments={audioFlag} t={t} onSeek={seek} />
        </div>
      )}
      {s.artifacts?.keyframe_ela && (
        <div className="card">
          <h3>Keyframe ELA @ {fmtTs(s.keyframe_t)}</h3>
          <img src={fileUrl(c.id, s.artifacts.keyframe_ela)} alt="keyframe ELA" style={{ maxWidth: "100%", maxHeight: 360, borderRadius: 8 }} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ audio */
function AudioView({ c, ev, s, findings, focus }) {
  const { ref, t, setT, seek } = useMedia(focus);
  const dur = s.duration || 1;
  const flagged = findings.filter((f) => f.detector === "audio_spoof_model").flatMap(intervalsOf);
  const allSegs = findings.flatMap(intervalsOf);
  const lanes = audioLanes(s, findings);
  const curves = s.curves;
  if (curves) {
    const norm = (arr) => { const mn = Math.min(...arr), mx = Math.max(...arr); return arr.map((v) => (v - mn) / (mx - mn || 1)); };
    lanes.push({ name: "Energy (RMS dB)", color: "var(--accent)", kind: "series", items: norm(curves.rms_db).map((v, i) => ({ t: i * curves.t_step, v })) });
    lanes.push({ name: "Zero-crossing rate", color: "var(--c-text)", kind: "series", items: norm(curves.zcr).map((v, i) => ({ t: i * curves.t_step, v })) });
    lanes.push({ name: "MFCC dynamics", color: "var(--c-image)", kind: "series", items: norm(curves.mfcc_delta).map((v, i) => ({ t: i * curves.t_step, v })) });
  }
  const src = s.preview ? fileUrl(c.id, s.preview) : fileUrl(c.id, ev.stored_as);
  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid g-main">
        <div className="card">
          <audio ref={ref} src={src} controls style={{ width: "100%", marginBottom: 12 }} onTimeUpdate={(e) => setT(e.target.currentTime)} />
          {s.artifacts?.spectrogram && <Spectrogram src={fileUrl(c.id, s.artifacts.spectrogram)} duration={dur} segments={allSegs} t={t} onSeek={seek} />}
          <div className="muted small" style={{ marginTop: 6 }}>{dur}s · speech in {Math.round((s.speech_ratio || 0) * 100)}% of frames · red bands = flagged segments</div>
        </div>
        <FindingList findings={findings} onSeek={seek} />
      </div>
      <div className="card">
        <h3>Signal timeline · click to seek</h3>
        <Timeline duration={dur} lanes={lanes} current={t} onSeek={seek} />
      </div>
      <div className="card">
        <h3>Transcript (Whisper)</h3>
        <Transcript tr={s.transcript} flagged={flagged} t={t} onSeek={seek} />
      </div>
    </div>
  );
}
