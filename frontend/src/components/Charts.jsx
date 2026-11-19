import React from "react";
import { fmtTs, scoreColor } from "../api.js";

/** Horizontal 0–1 scale with the fused score, its uncertainty band and verdict zones. */
export function RangeGauge({ score, interval, height = 54 }) {
  const W = 520, pad = 14, y = 22, x = (v) => pad + v * (W - 2 * pad);
  const [lo, hi] = interval || [score, score];
  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" style={{ maxWidth: 560 }} role="img"
      aria-label={`Score ${score} with uncertainty ${lo} to ${hi}`}>
      <defs>
        <linearGradient id="gz" x1="0" x2="1">
          <stop offset="0" stopColor="var(--green)" stopOpacity=".55" />
          <stop offset=".45" stopColor="var(--amber)" stopOpacity=".55" />
          <stop offset=".75" stopColor="var(--orange)" stopOpacity=".6" />
          <stop offset="1" stopColor="var(--red)" stopOpacity=".7" />
        </linearGradient>
      </defs>
      <rect x={pad} y={y - 4} width={W - 2 * pad} height={8} rx={4} fill="url(#gz)" />
      <rect x={x(lo)} y={y - 10} width={Math.max(2, x(hi) - x(lo))} height={20} rx={4}
        fill="rgba(255,255,255,.12)" stroke="#fff" strokeOpacity=".6" />
      <circle cx={x(score)} cy={y} r={7} fill={scoreColor(score)} stroke="#fff" strokeWidth="2" />
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <text key={t} x={x(t)} y={y + 26} fontSize="10" fill="var(--muted)" textAnchor="middle">{t.toFixed(2)}</text>
      ))}
      <text x={pad} y={10} fontSize="10" fill="var(--muted)">no indication</text>
      <text x={W - pad} y={10} fontSize="10" fill="var(--muted)" textAnchor="end">strong indication</text>
    </svg>
  );
}

export function Meter({ value, color, width = "100%" }) {
  return (
    <div className="meter" style={{ width }}>
      <div style={{ width: `${Math.round((value || 0) * 100)}%`, background: color || scoreColor(value) }} />
    </div>
  );
}

/**
 * Multi-lane timeline shared by video & audio evidence.
 * lane: { name, color, kind: "segments"|"points"|"series", items }
 *   segments: [{start,end,score?,label?}]  points: [{t,label?}]  series: [{t,v}] (v in 0..1)
 */
export function Timeline({ duration, lanes, current, onSeek }) {
  const W = 1000, labelW = 150, laneH = 30, H = lanes.length * laneH + 26;
  const x = (t) => labelW + (Math.min(Math.max(t, 0), duration) / (duration || 1)) * (W - labelW - 8);
  const ticks = [];
  const step = duration > 120 ? 30 : duration > 40 ? 10 : duration > 12 ? 5 : 1;
  for (let t = 0; t <= duration; t += step) ticks.push(t);
  const click = (e) => {
    if (!onSeek) return;
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    if (px < labelW) return;
    onSeek(((px - labelW) / (W - labelW - 8)) * duration);
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" onClick={click} style={{ cursor: onSeek ? "pointer" : "default" }}>
      {lanes.map((l, i) => {
        const y0 = i * laneH + 4;
        return (
          <g key={l.name}>
            <rect x={labelW} y={y0} width={W - labelW - 8} height={laneH - 8} rx={4} fill="var(--panel-2)" />
            <circle cx={10} cy={y0 + (laneH - 8) / 2} r={4} fill={l.color} />
            <text x={20} y={y0 + (laneH - 8) / 2 + 4} fontSize="12" fill="var(--text)">{l.name}</text>
            {l.kind === "segments" && l.items.map((s, k) => (
              <rect key={k} x={x(s.start)} y={y0} width={Math.max(3, x(s.end) - x(s.start))} height={laneH - 8} rx={3}
                fill={l.color} fillOpacity={0.25 + 0.6 * (s.score ?? 0.6)}>
                <title>{`${s.label || l.name}: ${fmtTs(s.start)}–${fmtTs(s.end)}${s.score != null ? ` (score ${s.score.toFixed(2)})` : ""}`}</title>
              </rect>
            ))}
            {l.kind === "points" && l.items.map((p, k) => (
              <g key={k}>
                <line x1={x(p.t)} x2={x(p.t)} y1={y0} y2={y0 + laneH - 8} stroke={l.color} strokeWidth="3" />
                <title>{`${p.label || l.name} @ ${fmtTs(p.t)}`}</title>
              </g>
            ))}
            {l.kind === "series" && l.items.length > 1 && (() => {
              const pts = l.items.filter((p) => p.v != null);
              if (pts.length < 2) return null;
              const yy = (v) => y0 + (laneH - 8) * (1 - v);
              const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.t).toFixed(1)},${yy(p.v).toFixed(1)}`).join(" ");
              return (
                <g>
                  <line x1={labelW} x2={W - 8} y1={yy(0.65)} y2={yy(0.65)} stroke="var(--red)" strokeDasharray="3 3" strokeOpacity=".5" />
                  <path d={`${d} L${x(pts[pts.length - 1].t)},${yy(0)} L${x(pts[0].t)},${yy(0)} Z`} fill={l.color} fillOpacity=".18" />
                  <path d={d} fill="none" stroke={l.color} strokeWidth="1.8" />
                  {pts.filter((p) => p.v >= 0.65).map((p, k) => <circle key={k} cx={x(p.t)} cy={yy(p.v)} r="2.5" fill="var(--red)" />)}
                </g>
              );
            })()}
          </g>
        );
      })}
      {ticks.map((t) => (
        <text key={t} x={x(t)} y={H - 6} fontSize="10" fill="var(--muted)" textAnchor="middle">{fmtTs(t).replace(/\.\d$/, "")}</text>
      ))}
      {current != null && <line x1={x(current)} x2={x(current)} y1={0} y2={H - 18} stroke="#fff" strokeWidth="1.5" />}
    </svg>
  );
}

/** Two normalised series (mouth motion vs speech energy) for the AV-sync panel. */
export function DualSeries({ series, height = 120 }) {
  if (!series) return null;
  const W = 1000, H = height, n = series.mouth.length;
  const vals = [...series.mouth, ...series.audio].filter((v) => v != null);
  const mx = Math.max(2.5, ...vals.map(Math.abs));
  const x = (i) => (i / Math.max(1, n - 1)) * W;
  const y = (v) => H / 2 - (v / mx) * (H / 2 - 6);
  const path = (arr) => {
    let d = "", pen = false;
    arr.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
      pen = true;
    });
    return d;
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="none" style={{ height }}>
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--line)" />
      <path d={path(series.audio)} fill="none" stroke="var(--c-audio)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
      <path d={path(series.mouth)} fill="none" stroke="var(--c-video)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function LagCurve({ curve, best }) {
  if (!curve?.length) return null;
  const W = 300, H = 90;
  const lags = curve.map((c) => c.lag), mn = Math.min(...lags), mx = Math.max(...lags);
  const x = (l) => ((l - mn) / (mx - mn || 1)) * (W - 20) + 10;
  const y = (c) => H / 2 - (c ?? 0) * (H / 2 - 8);
  const d = curve.filter((c) => c.corr != null).map((c, i) => `${i ? "L" : "M"}${x(c.lag)},${y(c.corr)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H + 14}`} width="100%" style={{ maxWidth: 340 }}>
      <line x1="10" x2={W - 10} y1={H / 2} y2={H / 2} stroke="var(--line)" />
      <line x1={x(0)} x2={x(0)} y1="4" y2={H - 4} stroke="var(--muted)" strokeDasharray="2 3" />
      <path d={d} fill="none" stroke="var(--c-cross)" strokeWidth="2" />
      {best != null && <line x1={x(best)} x2={x(best)} y1="4" y2={H - 4} stroke="var(--accent)" />}
      <text x="10" y={H + 12} fontSize="10" fill="var(--muted)">{(mn * 1000).toFixed(0)} ms</text>
      <text x={W / 2} y={H + 12} fontSize="10" fill="var(--muted)" textAnchor="middle">lag</text>
      <text x={W - 10} y={H + 12} fontSize="10" fill="var(--muted)" textAnchor="end">+{(mx * 1000).toFixed(0)} ms</text>
    </svg>
  );
}
