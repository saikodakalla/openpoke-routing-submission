"use client";
import { useEffect, useState } from "react";
import type { Candidate, Trace } from "./types";
type Point = {
  id: string;
  title: string;
  owner: string;
  state: string;
  x: number;
  y: number;
};
type Projection = {
  deferred?: boolean;
  label: string;
  model: string;
  dimension: number;
  explained_variance: number;
  points: Point[];
  query?: { request_id: string; x: number; y: number } | null;
  sampled?: boolean;
};
export default function VectorExplorer({
  trace,
  requestId,
  candidates: live = [],
  refreshKey = "",
}: {
  trace: Trace | null;
  requestId?: string;
  candidates?: Candidate[];
  refreshKey?: string;
}) {
  const [data, setData] = useState<Projection | null>(null);
  const [selected, setSelected] = useState<Point | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setData(null);
    setSelected(null);
    const id = requestId || trace?.request_id;
    fetch(
      `/api/routing/vectors${id ? `?request_id=${encodeURIComponent(id)}` : ""}`,
      { signal: controller.signal },
    )
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            "Could not load stored vectors. Run the index command and retry.",
          );
        setData(await r.json());
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [requestId, trace?.request_id, refreshKey]);
  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p role="status">Projecting stored vectors…</p>;
  if (!data.points.length)
    return (
      <p>
        {data.label ||
          "Semantic memory has not been needed yet. A complex request builds it on demand."}
      </p>
    );
  const maxX = Math.max(
    ...data.points.map((p) => Math.abs(p.x)),
    Math.abs(data.query?.x || 0),
    0.1,
  );
  const maxY = Math.max(
    ...data.points.map((p) => Math.abs(p.y)),
    Math.abs(data.query?.y || 0),
    0.1,
  );
  const matches = live.length ? live : trace?.candidates || [];
  const candidates = new Set(
    matches.filter((c) => c.similarity != null).map((c) => c.task_id),
  );
  const cosine = matches.find((c) => c.task_id === selected?.id)?.similarity;
  return (
    <section
      className="vector-explorer"
      aria-label="Vector database representation"
    >
      <details className="embedding-factors">
        <summary>What the embeddings represent</summary>
        <p>
          Each vector encodes a task title and summary with {data.model} (
          {data.dimension} dimensions). The same model embeds the request.
          {data.model.startsWith("fixture-")
            ? " Offline signed feature hashing tests the storage and retrieval plumbing; it does not measure semantic understanding."
            : " Learned coordinates represent semantic relationships."}{" "}
          Contacts, dates, task state and owner IDs remain explicit SQLite
          evidence, even when names appear in task prose.
        </p>
        <p>
          Chroma uses cosine distance, with a shortlist of 10 and one bounded
          expansion to 30. Similarity alone cannot authorize reuse. The verifier
          requires compatible ownership evidence, a minimum score and a lead
          over alternatives.
        </p>
        <p>
          Vectors are cached by exact text, model and dimension, version checked
          against SQLite, and rebuilt when summaries change. PCA compresses the
          current stored vectors for inspection; its plotted distance does not
          determine the routing decision.
        </p>
      </details>
      <div className="section-heading">
        <h3>Inside the vector index</h3>
      </div>
      <p>
        PCA · {data.dimension}D → 2D ·{" "}
        {(100 * data.explained_variance).toFixed(1)}% variance retained
      </p>
      <label className="vector-task-picker">
        Inspect a stored task
        <select
          aria-label="Inspect a stored task"
          value={selected?.id || ""}
          onChange={(e) =>
            setSelected(
              data.points.find((p) => p.id === e.target.value) || null,
            )
          }
        >
          <option value="">Choose a task…</option>
          {data.points.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title} · {p.id}
            </option>
          ))}
        </select>
      </label>
      {data.sampled && (
        <p>
          Background tasks are sampled; this request’s retrieved tasks are
          included.
        </p>
      )}
      <svg
        viewBox="0 0 520 330"
        role="group"
        aria-label="PCA projection of stored task vectors"
      >
        <line x1="25" y1="165" x2="495" y2="165" stroke="#ced7e3" />
        <line x1="260" y1="20" x2="260" y2="310" stroke="#ced7e3" />
        <text x="462" y="184" fill="#52617b" fontSize="11">
          PC 1
        </text>
        <text x="268" y="30" fill="#52617b" fontSize="11">
          PC 2
        </text>
        {data.query && (
          <g aria-label="Your request vector">
            {data.points
              .filter((p) => candidates.has(p.id))
              .map((p) => (
                <line
                  key={p.id}
                  x1={260 + (data.query!.x / maxX) * 225}
                  y1={165 - (data.query!.y / maxY) * 140}
                  x2={260 + (p.x / maxX) * 225}
                  y2={165 - (p.y / maxY) * 140}
                  stroke="#2963d9"
                  strokeOpacity="0.18"
                  strokeDasharray="3 4"
                />
              ))}
          </g>
        )}
        {[...data.points]
          .sort(
            (a, b) =>
              Number(candidates.has(a.id)) - Number(candidates.has(b.id)),
          )
          .map((p) => (
            <circle
              key={p.id}
              cx={260 + (p.x / maxX) * 225}
              cy={165 - (p.y / maxY) * 140}
              r={p.id === selected?.id ? 7 : candidates.has(p.id) ? 5 : 2.5}
              fill={
                p.id === trace?.task_id
                  ? "#16755a"
                  : candidates.has(p.id)
                    ? "#2963d9"
                    : "#91a3bb"
              }
              opacity={candidates.has(p.id) ? 1 : 0.5}
              role="button"
              tabIndex={candidates.has(p.id) ? 0 : -1}
              aria-label={`${p.title}, ${p.id}`}
              onClick={() => setSelected(p)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelected(p);
                }
              }}
            >
              <title>
                {p.title} · {p.id}
              </title>
            </circle>
          ))}
        {data.query && (
          <g
            transform={`translate(${260 + (data.query.x / maxX) * 225}, ${165 - (data.query.y / maxY) * 140})`}
            aria-label="Projected request"
          >
            <path
              d="M0 -7 7 0 0 7 -7 0Z"
              fill="#242424"
              stroke="white"
              strokeWidth="2"
            />
            <title>Your request, projected using the same PCA axes</title>
          </g>
        )}
      </svg>
      <div className="legend">
        <span>● Stored tasks</span>
        {data.query && <span>◆ Your request</span>}
        <span className="blue">● Retrieved candidates</span>
        <span className="green">● Selected task</span>
      </div>
      {selected && (
        <div className="point-detail">
          <strong>{selected.title}</strong>
          <p>{selected.owner}</p>
          <code>{selected.id}</code>
          <p>
            Original-space cosine:{" "}
            {cosine == null
              ? "not retrieved for this request"
              : cosine.toFixed(4)}
          </p>
        </div>
      )}
      <p className="small-note">
        Current stored index; the table retains this request’s original
        evidence. {data.model}.{" "}
        {data.model.startsWith("fixture") ? "Offline test embeddings. " : ""}
        Lines link the request to retrieved tasks; line length is not a
        similarity score. This projection is illustrative. Nearby points do not
        prove ownership; cosine and metadata are evaluated in the routing trace.
      </p>
    </section>
  );
}
