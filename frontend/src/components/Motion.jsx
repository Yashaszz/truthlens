import React, { useEffect, useRef, useState } from "react";

const reduced = () => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
};

/** Animated number: counts from 0 to `value` once when it first appears. */
export function CountUp({ value, duration = 1100, decimals = 0, suffix = "" }) {
  const [v, setV] = useState(reduced() ? value : 0);
  useEffect(() => {
    if (reduced()) { setV(value); return; }
    let raf, t0;
    const step = (t) => {
      t0 = t0 ?? t;
      const k = Math.min(1, (t - t0) / duration);
      setV(value * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <>{v.toFixed(decimals)}{suffix}</>;
}

/** Red line-art scene for fake verdicts: a revolver draws itself, spins, fires, the "REAL" board falls, "FAKE" pops up. */
function FakeShot() {
  const root = useRef(null);
  useEffect(() => {
    // bullet travels exactly from the muzzle to the board, whatever the layout width
    const el = root.current;
    const b = el?.querySelector(".bullet"), w = el?.querySelector(".board-wrap");
    if (b && w) el.style.setProperty("--shot-dist", `${Math.max(40, w.getBoundingClientRect().left + 30 - b.getBoundingClientRect().left)}px`);
  }, []);
  return (
    <div className="shot" aria-hidden="true" ref={root}>
      <svg className="gun" viewBox="0 0 200 124" width="210" height="130">
        <g className="gun-spin">
          <path className="ink" d="M58 30 H176 V44 H58 Z M168 30 V24 H174 V30" />
          <path className="ink" d="M36 28 H60 V60 H36 Z" />
          <circle className="ink" cx="48" cy="44" r="13" />
          <circle className="ink thin" cx="48" cy="37" r="2.6" /><circle className="ink thin" cx="54" cy="48" r="2.6" /><circle className="ink thin" cx="42" cy="48" r="2.6" />
          <path className="ink" d="M40 60 L32 108 Q30 117 41 117 H58 Q66 117 63 106 L60 66" />
          <path className="ink" d="M60 64 Q78 63 80 77 Q80 88 66 88" />
          <path className="ink thin" d="M66 67 Q72 73 67 81" />
          <path className="ink" d="M36 30 L26 19 L33 16 L42 27" />
          <path className="ink thin" d="M38 82 L52 82 M37 92 L51 92 M36 102 L50 102" />
        </g>
        <g className="flash" transform="translate(184 37)">
          <path d="M0 0 L14 -9 L9 -2 L22 0 L9 2 L14 9 Z" />
        </g>
      </svg>
      <span className="bullet" />
      <div className="board-wrap">
        <svg className="board" viewBox="0 0 170 130" width="170" height="130">
          <path className="string" d="M30 4 L52 40 M140 4 L118 40" />
          <rect x="18" y="40" width="134" height="70" rx="6" />
          <text x="85" y="88" textAnchor="middle">REAL</text>
        </svg>
        <span className="fake-btn">FAKE</span>
      </div>
    </div>
  );
}

/** Plays once: green outline sweep for genuine media; red sweep + revolver scene for fakes. */
export function VerdictReveal({ play, fake, children }) {
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (!play || reduced()) return;
    setActive(true);
    const t = setTimeout(() => setActive(false), fake ? 5600 : 3600);
    return () => clearTimeout(t);
  }, [play, fake]);
  return (
    <div className={`reveal ${active ? `reveal-on ${fake ? "reveal-fake" : "reveal-real"}` : ""}`}>
      {children}
      {active && fake && <FakeShot />}
      {active && !fake && <span className="reveal-badge">Looks genuine</span>}
    </div>
  );
}
