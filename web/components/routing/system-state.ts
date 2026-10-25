import type { Activity, Candidate, Trace } from "./types";

export type Layer =
  | "request"
  | "lookup"
  | "embedding"
  | "vector"
  | "verify"
  | "execution"
  | "clarify";
export type LayerState =
  | "waiting"
  | "active"
  | "complete"
  | "skipped"
  | "failed"
  | "blocked";
const layers: Layer[] = [
  "request",
  "lookup",
  "embedding",
  "vector",
  "verify",
  "execution",
  "clarify",
];
const mapping: Record<string, Layer> = {
  lookup: "lookup",
  context: "lookup",
  language: "request",
  index: "embedding",
  execution: "execution",
  ownership_check: "lookup",
  metadata: "lookup",
  keyword: "lookup",
  embedding: "embedding",
  vector: "vector",
  retrieval: "vector",
  verify: "verify",
  ownership: "execution",
  model: "execution",
  tool: "execution",
  clarify: "clarify",
};

// State is reduced from observed operations, never elapsed time or invented model reasoning.
export function systemState(
  events: Activity[],
  pending: boolean,
  trace?: Trace,
  error?: string,
) {
  const states = Object.fromEntries(
    layers.map((layer) => [layer, "waiting"]),
  ) as Record<Layer, LayerState>;
  states.request = "complete";
  const operations = new Map<string, Activity>();
  for (const event of events) operations.set(event.operation_id, event);
  let current: Layer = "request";
  for (const event of operations.values()) {
    let layer = mapping[event.kind];
    if (!layer) continue;
    // Keyword verification belongs to the direct lookup layer. The lower verifier
    // in the architecture is reached only after an actual Chroma search.
    if (
      event.kind === "verify" &&
      !events.some((prior) => prior.kind === "vector" && prior.id < event.id)
    )
      layer = "lookup";
    current = layer;
    // A later completed tool must not conceal an earlier failed tool.
    if (states[layer] !== "failed")
      states[layer] =
        event.status === "failed"
          ? "failed"
          : event.status === "started"
            ? pending
              ? "active"
              : "failed"
            : "complete";
  }
  if (trace) {
    if (trace.path !== "vector") {
      states.embedding = "skipped";
      states.vector = "skipped";
      states.verify = "skipped";
    }
    if (trace.decision === "clarify") {
      states.clarify = "complete";
      states.execution = "skipped";
      current = "clarify";
    } else if (trace.task_id) {
      states.clarify = "skipped";
      const status = trace.execution.status;
      states.execution =
        states.execution === "failed" || status === "failed"
          ? "failed"
          : status === "blocked"
            ? "blocked"
            : status === "running"
              ? "active"
              : ["completed", "awaiting_approval"].includes(status)
                ? "complete"
                : "waiting";
      current = "execution";
    }
  }
  if (!pending && error) states[current] = "failed";
  const active = [...operations.values()]
    .reverse()
    .find(
      (event) =>
        event.status === "started" &&
        operations.get(event.operation_id)?.status === "started",
    );
  return {
    states,
    current,
    label: pending
      ? active?.label || "Receiving request"
      : error
        ? "Request interrupted"
        : trace?.decision === "clarify"
          ? trace.routing_status === "answered"
            ? "Clarification answered"
            : "Waiting for your answer"
          : trace
            ? trace.execution.status.replaceAll("_", " ")
            : "Request recorded",
  };
}

export function liveCandidates(events: Activity[], trace?: Trace): Candidate[] {
  for (const event of [...events].reverse()) {
    if (event.kind !== "candidates" || event.status !== "completed") continue;
    const detail = event.detail as { candidates?: Candidate[] } | null;
    if (detail?.candidates) return detail.candidates;
  }
  return trace?.candidates || [];
}
