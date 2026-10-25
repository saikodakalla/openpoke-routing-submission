"use client";
import type { Activity } from "@/components/routing/types";

export function ActivityLog({
  events,
  busy,
  failed,
}: {
  events: Activity[];
  busy: boolean;
  failed?: boolean;
}) {
  const operations = new Map<string, Activity>();
  for (const event of events) {
    const previous = operations.get(event.operation_id);
    operations.set(event.operation_id, {
      ...event,
      detail: event.detail ?? previous?.detail,
    });
  }
  const steps = Array.from(operations.values());
  const current = [...steps]
    .reverse()
    .find((step) => step.status === "started");
  const summary = busy
    ? current?.label || "Working on your request"
    : failed
      ? "Couldn’t complete the request"
      : steps.some(
            (s) =>
              s.kind === "tool" &&
              (s.detail as { tool?: string } | null)?.tool === "prepare_order",
          )
        ? "Prepared your saved order"
        : steps.some((s) => s.kind === "vector")
          ? "Searched task memory"
          : "Checked saved context";
  return (
    <details className="activity-log">
      <summary>
        <span
          className={
            busy
              ? "activity-spinner"
              : failed
                ? "activity-failed"
                : "activity-check"
          }
          aria-hidden="true"
        >
          {busy ? "" : failed ? "!" : "✓"}
        </span>
        <span role={busy ? "status" : undefined}>
          {summary}
          {busy ? "…" : ""}
        </span>
        <svg
          className="activity-chevron"
          viewBox="0 0 16 16"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="m5 6 3 3 3-3"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
        </svg>
      </summary>
      <ol aria-label="Request activity">
        {steps.map((step) => (
          <li key={step.operation_id} data-state={step.status}>
            <span
              className={
                busy && step.status === "started"
                  ? "activity-spinner small"
                  : "step-mark"
              }
              aria-hidden="true"
            >
              {step.status === "failed"
                ? "!"
                : step.status === "completed"
                  ? "✓"
                  : "·"}
            </span>
            <div>
              <span>{step.label}</span>
              <small>
                {step.status === "failed"
                  ? "Failed"
                  : step.status === "started"
                    ? busy
                      ? "In progress"
                      : "Interrupted"
                    : "Complete"}
              </small>
              {step.detail != null && (
                <details className="operation-detail">
                  <summary>Details</summary>
                  <pre>
                    {typeof step.detail === "string"
                      ? step.detail
                      : JSON.stringify(step.detail, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
