"use client";
// THESIS: the architecture is an inspectable explanation of each real request.
// OWN-WORLD: the chat's neutral canvas, quiet connectors, blue active layers.
// STORY: follow lookup, inspect retrieval, understand the task → agent decision.
// FIRST VIEWPORT: request selector and live flow, retrieval appears when observed.
// FORM: optional split pane; full-width inspection on narrow screens.
import { useId, useState } from "react";
import dynamic from "next/dynamic";
import type { Turn } from "@/components/conversation/MessageTurn";
import type { Candidate } from "./types";
import { SystemFlow } from "./SystemFlow";
import { liveCandidates, systemState } from "./system-state";
const RegistryExplorer = dynamic(() => import("./RegistryExplorer"));
const VectorExplorer = dynamic(() => import("./VectorExplorer"));
const RoutingPanel = dynamic(() =>
  import("./RoutingPanel").then((m) => m.RoutingPanel),
);

export function SystemView({
  turns,
  selected,
  onSelect,
  onClose,
}: {
  turns: Turn[];
  selected: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const heading = useId();
  const [inspection, setInspection] = useState<
    "flow" | "rows" | "schema" | "vectors"
  >("flow");
  const turn =
    turns.find((item) => item.requestId === selected) || turns.at(-1);
  const events = turn?.activity || [];
  const trace = turn?.trace;
  const pending = Boolean(turn?.pending);
  const { states, label } = systemState(events, pending, trace, turn?.error);
  const vectorUsed =
    events.some((event) => event.kind === "vector") ||
    Boolean(
      trace?.candidates.some((candidate) => candidate.similarity != null),
    );
  const candidates = liveCandidates(events, trace);
  const retrievedEvent = [...events]
    .reverse()
    .find((event) => event.kind === "retrieval");
  const retrieved = [
    ...new Map(
      events
        .filter((event) => event.kind === "retrieval")
        .flatMap(
          (event) =>
            (event.detail as { candidates?: Candidate[] } | null)?.candidates ||
            [],
        )
        .map((candidate) => [candidate.task_id, candidate]),
    ).values(),
  ];
  const compared = [
    ...candidates,
    ...retrieved.filter(
      (item) =>
        !candidates.some((candidate) => candidate.task_id === item.task_id),
    ),
  ];
  const ownerEvent = events.find((event) => event.kind === "ownership");
  const owner = ownerEvent?.detail as {
    task_id?: string;
    owner?: string;
  } | null;
  const taskId = trace?.task_id || owner?.task_id;
  const ownerName = trace?.owner || owner?.owner;
  const clarified =
    trace?.decision === "clarify" ||
    events.some((event) => event.kind === "clarify");
  return (
    <aside className="system-view" aria-labelledby={heading}>
      <div className="system-heading">
        <div>
          <h2 id={heading}>System view</h2>
          <p>Follow the work behind each reply</p>
        </div>
        <button
          className="system-close"
          onClick={onClose}
          aria-label="Close system view"
        >
          ✕
        </button>
      </div>
      {turn ? (
        <label className="request-picker">
          Inspect request
          <select
            aria-label="Inspect request"
            value={turn.requestId}
            onChange={(event) => onSelect(event.target.value)}
          >
            {turns.map((item, i) => (
              <option value={item.requestId} key={item.requestId}>
                {i + 1}. {item.text.slice(0, 110)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="system-empty">
          Send a message to follow its path through the system.
        </p>
      )}
      <nav className="inspection-tabs" aria-label="System inspection">
        {(
          [
            ["flow", "Flow"],
            ["rows", "Database"],
            ["schema", "Schema"],
            ["vectors", "Vectors"],
          ] as const
        ).map(([view, name]) => (
          <button
            key={view}
            aria-pressed={inspection === view}
            onClick={() => setInspection(view)}
          >
            {name}
          </button>
        ))}
      </nav>
      {inspection === "rows" || inspection === "schema" ? (
        <RegistryExplorer key={inspection} initialMode={inspection} />
      ) : inspection === "vectors" ? (
        <VectorExplorer
          trace={trace || null}
          requestId={vectorUsed ? turn?.requestId : undefined}
          candidates={compared}
        />
      ) : (
        <>
          <div className="system-stage" role="status" aria-live="polite">
            <span
              className={pending ? "activity-spinner" : "system-status-dot"}
              aria-hidden="true"
            />
            <span>{turn ? label : "Ready for your request"}</span>
            {trace && (
              <small>
                {trace.mode === "offline" ? "Offline test mode" : "Live model"}
              </small>
            )}
          </div>
          {vectorUsed && (
            <button
              className="jump-retrieval"
              onClick={() =>
                document
                  .getElementById("system-vector-retrieval")
                  ?.scrollIntoView({ block: "start" })
              }
            >
              View vector retrieval ↓
            </button>
          )}
          <SystemFlow
            onInspect={(layer) =>
              setInspection(layer === "lookup" ? "rows" : "vectors")
            }
            states={states}
            hasRequest={Boolean(turn)}
            vectorUsed={vectorUsed}
            owner={Boolean(taskId)}
            clarified={clarified}
            answered={trace?.routing_status === "answered"}
          />
          <div className="flow-key">
            <span>Blue: running</span>
            <span>Green: completed</span>
            <span>Gray: waiting / skipped</span>
          </div>
          {turn && (
            <ol className="layer-statuses" aria-label="System layers">
              {(
                [
                  ["lookup", "Task registry"],
                  ["embedding", "Request embedding"],
                  ["vector", "Vector retrieval"],
                  ["verify", "Fallback verification"],
                  ["execution", "Execution agent"],
                  ["clarify", "Clarification"],
                ] as const
              ).map(([layer, name]) => (
                <li key={layer} data-state={states[layer]}>
                  <span>{name}</span>
                  <span>
                    {states[layer] === "skipped"
                      ? "Bypassed"
                      : states[layer] === "waiting"
                        ? "Not reached"
                        : states[layer] === "active"
                          ? "Running"
                          : states[layer] === "blocked"
                            ? "Blocked"
                            : states[layer] === "failed"
                              ? "Failed / interrupted"
                              : "Complete"}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {taskId && (
            <section
              className="selected-owner"
              aria-label="Selected task and agent"
            >
              <h3>Task → owning agent</h3>
              <p>
                {trace?.candidates.find(
                  (candidate) => candidate.task_id === taskId,
                )?.title || taskId}
              </p>
              <strong>{ownerName}</strong>
              <small>{taskId}</small>
              {trace?.new_agent_created && (
                <p>New work confirmed; task and owner registered.</p>
              )}
            </section>
          )}
          {vectorUsed && turn && (
            <section
              className="system-retrieval"
              id="system-vector-retrieval"
              aria-label="Request retrieval"
            >
              <h3>Vector retrieval</h3>
              <p className="small-note">
                Tasks are retrieved first. Verified ownership links determine
                which execution agent receives the work.
              </p>
              <VectorExplorer
                key={turn.requestId}
                trace={trace || null}
                requestId={turn.requestId}
                candidates={compared}
                refreshKey={String(retrievedEvent?.id || "waiting")}
              />
              {(candidates.length > 0 || retrieved.length > 0) && (
                <div className="retrieval-table-wrap">
                  <table className="retrieval-table">
                    <caption>Retrieved and verified tasks</caption>
                    <thead>
                      <tr>
                        <th scope="col">Task / agent</th>
                        <th scope="col">Cosine</th>
                        <th scope="col">Verification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(candidates.length ? candidates : retrieved).map(
                        (candidate) => (
                          <tr
                            key={candidate.task_id}
                            data-selected={candidate.task_id === taskId}
                          >
                            <td>
                              <strong>{candidate.title}</strong>
                              <small>{candidate.owner}</small>
                              <code>{candidate.task_id}</code>
                            </td>
                            <td>
                              {candidate.similarity == null
                                ? "—"
                                : candidate.similarity.toFixed(4)}
                            </td>
                            <td>
                              {candidate.task_id === taskId
                                ? "Selected"
                                : candidate.conflicts?.length
                                  ? candidate.conflicts.join(", ")
                                  : candidate.ownership_supported
                                    ? "Supported"
                                    : candidate.score == null
                                      ? "Awaiting verification"
                                      : "Insufficient evidence"}
                              {candidate.score != null && (
                                <small>
                                  Score {candidate.score.toFixed(2)}
                                </small>
                              )}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
          {trace && (
            <details className="system-evidence">
              <summary>Scores, metadata and execution details</summary>
              <RoutingPanel trace={trace} busy={pending} hideVectorExplorer />
            </details>
          )}
          {turn?.error && (
            <p className="chat-error" role="alert">
              {turn.error}
            </p>
          )}
          {turn && <p className="system-request-id">{turn.requestId}</p>}
        </>
      )}
    </aside>
  );
}
