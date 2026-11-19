import React, { useEffect, useState } from "react";
import { api, Kind } from "../api.jsx";
import { useUI } from "../ui.jsx";

export default function SeenOnline({ c, onDone }) {
  const ui = useUI();
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const res = c.online;
  useEffect(() => { api.health().then(setHealth).catch(() => {}); }, []);
  const searchable = c.evidence.filter((e) => e.modality === "image" || e.modality === "video");
  const configured = health?.web_search;

  const run = async () => {
    setBusy(true);
    try { await api.online(c.id); await onDone(); ui.toast("Web search finished"); }
    catch (e) { ui.toast(e.message, "err"); }
    finally { setBusy(false); }
  };

  if (!searchable.length) return <div className="muted">Web search works on photos and videos.</div>;
  return (
    <div>
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <button className="btn ink" disabled={busy || !configured} onClick={run}>
          {busy ? <><span className="spin" style={{ borderTopColor: "var(--paper)" }} /> Searching the web…</> : res ? "Search again" : "Search the web for exact copies"}
        </button>
        <span className="small muted">
          {configured
            ? `Sends ${searchable.some((e) => e.modality === "video") ? "3 keyframes per video and " : ""}the image(s) to Google ${configured === "serpapi" ? "Lens via SerpAPI (temporary imgbb link, deleted after 10 min)" : "Cloud Vision"}. Only verified exact copies are listed.`
            : `Not set up yet: add ${(health?.web_search_missing || ["SERPAPI_KEY", "IMGBB_KEY"]).join(" + ")} to backend/.env and restart the server.`}
        </span>
      </div>
      {res && (
        <div style={{ marginTop: 18 }}>
          {res.fact_checks > 0 && (
            <div className="notice" style={{ borderLeftColor: "var(--red)", marginBottom: 14 }}>
              <b>Already covered by {res.fact_checks} fact-check article{res.fact_checks > 1 ? "s" : ""}.</b> See the links marked "Fact-check" below.
            </div>
          )}
          {Object.entries(res.items).map(([eid, r]) => {
            const e = c.evidence.find((x) => x.id === eid);
            return (
              <div key={eid} style={{ marginBottom: 18 }}>
                <div className="small" style={{ display: "flex", gap: 10, alignItems: "center", borderBottom: "1px solid var(--rule)", paddingBottom: 4, marginBottom: 6 }}>
                  <Kind m={e?.modality} /><b style={{ overflowWrap: "anywhere" }}>{e?.filename}</b>
                  <span className="muted">{r.frames_searched} frame(s) searched · {r.candidates ?? 0} candidates checked</span>
                </div>
                {r.fact_check_news?.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div className="label" style={{ color: "var(--red)", margin: "8px 0 2px" }}>Fact-checkers have flagged a fake version of this footage</div>
                    {r.fact_check_news.map((m) => (
                      <a key={m.link} className="hit" href={m.link} target="_blank" rel="noreferrer noopener" style={{ borderColor: "var(--red)" }}>
                        <span className="hit-body">
                          <span className="hit-top"><b>{m.site}</b><span className="tag strong">Fact-check</span>{m.date && <span className="muted small">{m.date}</span>}</span>
                          <span className="hit-title">{m.title}</span>
                          <span className="tiny muted" style={{ whiteSpace: "normal" }}>{m.snippet}</span>
                        </span>
                      </a>
                    ))}
                  </div>
                )}
                {r.status === "found" && <div className="label" style={{ margin: "8px 0 2px" }}>Where this footage appears ({r.matches.length})</div>}
                {r.status === "found" ? r.matches.map((m) => (
                  <a key={m.link} className="hit" href={m.link} target="_blank" rel="noreferrer noopener">
                    {m.thumb ? <img src={m.thumb} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span className="hit-ph" />}
                    <span className="hit-body">
                      <span className="hit-top">
                        <b>{m.site}</b>
                        {m.fact_check && <span className="tag strong">Fact-check</span>}
                        {m.date && <span className="muted small">{m.date}</span>}
                        <span className="muted small" style={{ marginLeft: "auto" }}>{m.match === "contains this footage" ? "contains this footage" : `${Math.round(m.similarity * 100)}% match`}</span>
                      </span>
                      <span className="hit-title">{m.title || m.link}</span>
                      <span className="tiny muted hit-url">{m.link}</span>
                    </span>
                  </a>
                )) : r.status === "partial" ? (
                  <div className="notice">No copies found, but {r.errors?.length} of {r.frames_searched} searches failed (network). Try "Search again".</div>
                ) : r.status === "none" ? (
                  <div className="muted">No exact copies found online.</div>
                ) : r.status === "not_configured" ? (
                  <div className="muted">Web search not configured.</div>
                ) : (
                  <div className="notice">Search failed: {(r.errors || []).join("; ") || "unknown error"}</div>
                )}
              </div>
            );
          })}
          <div className="footnote">Searched {res.at.replace("T", " ")} via {res.provider}. Only public, search-indexed pages appear (private chats and very recent posts may not).</div>
        </div>
      )}
    </div>
  );
}
