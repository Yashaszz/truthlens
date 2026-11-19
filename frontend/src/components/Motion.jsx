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

/** Ring + dot + short trail following the pointer (desktop only, respects reduced motion). */
export function CursorFollower() {
  const ring = useRef(null);
  const dot = useRef(null);
  const trail = useRef([]);
  const [on, setOn] = useState(false);

  useEffect(() => {
    let fine = false;
    try { fine = window.matchMedia("(pointer: fine)").matches; } catch { /* ignore */ }
    if (!fine || reduced()) return;
    setOn(true);
    const pos = { x: -100, y: -100 };
    const pts = [{ x: -100, y: -100 }, ...Array.from({ length: 4 }, () => ({ x: -100, y: -100 }))];
    let hover = false, down = false, raf;
    const move = (e) => {
      pos.x = e.clientX; pos.y = e.clientY;
      hover = !!e.target.closest?.("a, button, [role=radio], input, select, textarea, summary, .case-item, tr.click, .hit, .drop");
    };
    const md = () => { down = true; };
    const mu = () => { down = false; };
    const leave = () => { pos.x = -100; pos.y = -100; };
    const tick = () => {
      pts[0].x += (pos.x - pts[0].x) * 0.18; pts[0].y += (pos.y - pts[0].y) * 0.18;
      for (let i = 1; i < pts.length; i++) {
        pts[i].x += (pts[i - 1].x - pts[i].x) * 0.35; pts[i].y += (pts[i - 1].y - pts[i].y) * 0.35;
      }
      const s = hover ? 1.8 : down ? 0.7 : 1;
      if (ring.current) ring.current.style.transform = `translate3d(${pts[0].x}px, ${pts[0].y}px, 0) translate(-50%, -50%) scale(${s})`;
      if (ring.current) ring.current.classList.toggle("hover", hover);
      if (dot.current) dot.current.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0) translate(-50%, -50%)`;
      trail.current.forEach((el, i) => {
        if (el) el.style.transform = `translate3d(${pts[i + 1].x}px, ${pts[i + 1].y}px, 0) translate(-50%, -50%)`;
      });
      raf = requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerdown", md);
    window.addEventListener("pointerup", mu);
    document.addEventListener("pointerleave", leave);
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerdown", md);
      window.removeEventListener("pointerup", mu);
      document.removeEventListener("pointerleave", leave);
    };
  }, []);

  if (!on) return null;
  return (
    <div aria-hidden="true">
      {[0, 1, 2, 3].map((i) => <span key={i} className="cur-trail" style={{ opacity: 0.22 - i * 0.045, width: 6 - i, height: 6 - i }}
        ref={(el) => { trail.current[i] = el; }} />)}
      <span className="cur-ring" ref={ring} />
      <span className="cur-dot" ref={dot} />
    </div>
  );
}

/** Plays a one-time red (fake) or green (genuine) outline sweep around its child when `play` becomes true. */
export function VerdictReveal({ play, fake, children }) {
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (!play || reduced()) return;
    setActive(true);
    const t = setTimeout(() => setActive(false), 3600);
    return () => clearTimeout(t);
  }, [play]);
  return (
    <div className={`reveal ${active ? `reveal-on ${fake ? "reveal-fake" : "reveal-real"}` : ""}`}>
      {children}
      {active && <span className="reveal-badge">{fake ? "Fake detected" : "Looks genuine"}</span>}
    </div>
  );
}
