"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import type { Trace } from "./types";
const VectorExplorer = dynamic(() => import("./VectorExplorer"), {
  loading: () => <p>Opening vector explorer…</p>,
});
export function RoutingPanel({
  trace,
  busy,
  hideVectorExplorer = false,
}: {
  trace: Trace | null;
  busy: boolean;
  hideVectorExplorer?: boolean;
}) {
  const [vectors, setVectors] = useState(false);
  return (
    <aside className="evidence-panel" aria-label="Routing evidence">
      <div className="section-heading">
        <h2>Routing evidence</h2>
        <span className={busy ? "status amber" : "status"}>
          {busy ? "Resolving" : "Inspectable"}
        </span>
      </div>
      {!trace ? (
        <div className="evidence-empty">
          <div className="flow-preview">
            <span>Request</span>
            <b>↓</b>
            <span>Ownership lookup</span>
            <b>↓</b>
            <span>Retrieve & verify</span>
            <b>↓</b>
            <span>Reuse · Clarify · Create</span>
          </div>
          <p>
            Every request leaves a durable trace. Start with a sample, then
            inspect the path, evidence and execution outcome here.
          </p>
        </div>
      ) : (
        <>
          <div className="trace-summary">
            <span className={`decision ${trace.decision}`}>
              {trace.decision}
            </span>
            <div>
              <strong>
                {trace.path === "direct"
                  ? "Direct ownership"
                  : trace.path === "keyword"
                    ? "Keyword + verification"
                    : "Vector fallback + verification"}
              </strong>
              <p>
                {trace.new_agent_created
                  ? "New task and owner registered"
                  : trace.task_id
                    ? "Existing execution agent resumed"
                    : "Waiting for ownership evidence"}
              </p>
            </div>
          </div>
          <p className="request-id">{trace.request_id}</p>
          <div className="execution-state">
            <span>Execution</span>
            <strong>{trace.execution.status.replaceAll("_", " ")}</strong>
          </div>
          {trace.retrieval_error && (
            <p role="alert" className="error-text">
              {trace.retrieval_error}
            </p>
          )}
          {trace.verification && (
            <section
              aria-label="Candidate verifier checks"
              className="verifier-checks"
            >
              <h3>Candidate verifier</h3>
              <p className="small-note">{trace.verification.note}</p>
              <dl>
                {Object.entries(trace.verification.checks).map(
                  ([name, passed]) => (
                    <div key={name}>
                      <dt>{name.replaceAll("_", " ")}</dt>
                      <dd>{passed ? "Pass" : "Not established"}</dd>
                    </div>
                  ),
                )}
              </dl>
              <p>
                Winning margin: {trace.verification.actual_margin ?? "—"} /
                required {trace.verification.required_margin}. Conflicting
                candidates rejected: {trace.verification.rejected_conflicts}.
              </p>
            </section>
          )}
          <div className="section-heading candidates-heading">
            <h3>Candidate tasks</h3>
            <span>{trace.candidates.length} examined</span>
          </div>
          <p className="small-note">
            Scores are evidence weights, not probabilities. Threshold{" "}
            {trace.threshold}; ambiguity margin {trace.ambiguity_margin}.
          </p>
          <div className="candidate-list">
            {trace.candidates.map((c) => (
              <details
                key={c.task_id}
                className={
                  c.task_id === trace.task_id
                    ? "candidate selected"
                    : "candidate"
                }
              >
                <summary>
                  <span>
                    <strong>{c.title}</strong>
                    <small>{c.owner}</small>
                  </span>
                  <b>{c.score.toFixed(2)}</b>
                </summary>
                <div className="candidate-details">
                  <code>{c.task_id}</code>
                  <p>
                    {c.state} · v{c.version} · {c.start_date || "date unknown"}
                  </p>
                  {c.contacts.map((contact) => (
                    <p key={contact.email}>{contact.email}</p>
                  ))}
                  <p>
                    Threads: {c.threads.map((t) => t.id).join(", ") || "none"}
                  </p>
                  <p>
                    Ownership evidence:{" "}
                    {c.ownership_supported ? "supported" : "insufficient"}
                  </p>
                  {c.conflicts.length > 0 && (
                    <p className="error-text">{c.conflicts.join(" · ")}</p>
                  )}
                  <dl className="scores">
                    {Object.entries(c.components).map(([name, value]) => (
                      <div key={name}>
                        <dt>{name.replaceAll("_", " ")}</dt>
                        <dd>{value.toFixed(3)}</dd>
                      </div>
                    ))}
                    <div>
                      <dt>Original cosine</dt>
                      <dd>
                        {c.similarity == null
                          ? "not queried"
                          : c.similarity.toFixed(4)}
                      </dd>
                    </div>
                  </dl>
                  {c.evidence.length > 0 && (
                    <p>
                      {c.evidence.length} supporting history events inspected
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
          {trace.broader_search && (
            <p className="small-note">
              One broader search was attempted; contenders were kept in the
              comparison.
            </p>
          )}
          <details className="timings">
            <summary>Timings & provider usage</summary>
            <dl className="scores">
              {Object.entries(trace.timings_ms).map(([stage, ms]) => (
                <div key={stage}>
                  <dt>{stage.replaceAll("_", " ")}</dt>
                  <dd>{ms.toFixed(1)} ms</dd>
                </div>
              ))}
            </dl>
            <p>
              {trace.mode === "offline"
                ? "Deterministic fixtures · 0 external model calls · $0 provider cost"
                : `${trace.usage.length} logged provider attempts`}
            </p>
            {trace.usage.map((u, i) => (
              <p key={i}>
                {u.model} · {u.status} · {u.tokens} reserved tokens · $
                {u.cost_bound.toFixed(5)} estimated reservation
              </p>
            ))}
          </details>
        </>
      )}
      {!hideVectorExplorer && (
        <button
          className="vector-button"
          onClick={() => setVectors(!vectors)}
          aria-expanded={vectors}
        >
          <span aria-hidden="true">⠿</span>{" "}
          {vectors ? "Close vector explorer" : "Explore vector database"}{" "}
          <span aria-hidden="true">↗</span>
        </button>
      )}
      {!hideVectorExplorer && vectors && <VectorExplorer trace={trace} />}
    </aside>
  );
}
