const j = async (r) => {
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
};

export const api = {
  health: () => fetch("/api/health").then(j),
  cases: () => fetch("/api/cases").then(j),
  getCase: (id) => fetch(`/api/cases/${id}`).then(j),
  createCase: (form) => fetch("/api/cases", { method: "POST", body: form }).then(j),
  demo: () => fetch("/api/demo", { method: "POST" }).then(j),
  rerun: (id, body) => fetch(`/api/cases/${id}/rerun`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j),
  patchCase: (id, body) => fetch(`/api/cases/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(j),
  deleteCase: (id) => fetch(`/api/cases/${id}`, { method: "DELETE" }).then(j),
  review: (id, fid, body) =>
    fetch(`/api/cases/${id}/findings/${fid}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(j),
};

export const fileUrl = (caseId, rel) => `/api/cases/${caseId}/files/${rel}`;

export const fmtTs = (s) => {
  if (s == null) return "–";
  const m = Math.floor(s / 60);
  const sec = (s - m * 60).toFixed(1).padStart(4, "0");
  return `${String(m).padStart(2, "0")}:${sec}`;
};

export const BAND = {
  strong: { color: "var(--red)", short: "Strong indicators" },
  indicators: { color: "var(--orange)", short: "Possible manipulation" },
  inconclusive: { color: "var(--amber)", short: "Inconclusive" },
  none: { color: "var(--green)", short: "No significant indicators" },
};

export const MODALITY_COLOR = {
  image: "var(--c-image)", video: "var(--c-video)", audio: "var(--c-audio)",
  text: "var(--c-text)", "cross-modal": "var(--c-cross)",
};

export const KIND = { image: "Photo", video: "Video", audio: "Audio", text: "Text", "cross-modal": "Cross-check" };

export function Kind({ m }) {
  return <span className="kind" style={{ color: MODALITY_COLOR[m] || "var(--muted)" }}><i style={{ background: "currentColor" }} />{KIND[m] || m}</span>;
}

export const scoreColor = (s) =>
  s >= 0.7 ? "var(--red)" : s >= 0.55 ? "var(--orange)" : s >= 0.4 ? "var(--amber)" : "var(--green)";
