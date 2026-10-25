"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import type { Activity, Trace } from "@/components/routing/types";
import { ActivityLog } from "./ActivityLog";
const RoutingPanel = dynamic(() =>
  import("@/components/routing/RoutingPanel").then((m) => m.RoutingPanel),
);

export type Turn = {
  requestId: string;
  text: string;
  reply?: string;
  trace?: Trace;
  activity: Activity[];
  pending?: boolean;
  error?: string;
};
export function MessageTurn({
  turn,
  busy,
  onSend,
}: {
  turn: Turn;
  busy: boolean;
  onSend: (text: string, extra?: Record<string, unknown>) => void;
}) {
  const [inspect, setInspect] = useState(false);
  const trace = turn.trace;
  const drafts = trace?.current_drafts ?? trace?.execution.drafts ?? [];
  return (
    <article className="message-turn" aria-label="Conversation turn">
      <div className="user-message">
        <p>{turn.text}</p>
      </div>
      <div className="assistant-message">
        {(turn.activity.length > 0 || turn.pending) && (
          <ActivityLog
            events={turn.activity}
            busy={Boolean(turn.pending)}
            failed={Boolean(turn.error || trace?.execution.status === "failed")}
          />
        )}
        {turn.reply && <div className="assistant-text">{turn.reply}</div>}
        {turn.error && (
          <p className="chat-error" role="alert">
            {turn.error}
          </p>
        )}
        {(trace?.current_orders ?? trace?.execution.orders ?? [])
          .filter((order) => order.status === "prepared")
          .map((order) => (
            <section
              className="email-draft"
              key={order.id}
              aria-label="Prepared order"
            >
              <div className="draft-label">
                {order.merchant}
                <span>Awaiting your approval</span>
              </div>
              <p>{order.items}</p>
              <div className="draft-actions">
                <button
                  className="action-button primary"
                  disabled={busy}
                  onClick={() =>
                    onSend("Approve this order", {
                      task_id: trace?.task_id,
                      approval_order_id: order.id,
                    })
                  }
                >
                  Approve order
                </button>
                <span>Synthetic order</span>
              </div>
            </section>
          ))}
        {drafts
          .filter((draft) => draft.status === "draft")
          .map((draft) => (
            <section
              className="email-draft"
              key={draft.id}
              aria-label="Email draft"
            >
              <div className="draft-label">
                Email draft <span>Awaiting your approval</span>
              </div>
              <p className="draft-recipient">To: {draft.recipient}</p>
              <div className="draft-content">{draft.body}</div>
              <div className="draft-actions">
                <button
                  className="action-button primary"
                  disabled={busy}
                  onClick={() =>
                    onSend("Approve and send this draft", {
                      task_id: trace?.task_id,
                      approval_draft_id: draft.id,
                    })
                  }
                >
                  Approve and send
                </button>
                <span>Synthetic inbox</span>
              </div>
            </section>
          ))}
        {trace?.decision === "clarify" &&
          trace.clarification?.kind === "subject" &&
          trace.routing_status !== "answered" && (
            <button
              className="action-button new-task-action"
              disabled={busy}
              onClick={() =>
                onSend("This is new work. Start a new task.", {
                  new_work: true,
                })
              }
            >
              This is something new
            </button>
          )}
        {trace && (
          <div className="message-actions">
            <button
              onClick={() => setInspect(!inspect)}
              aria-expanded={inspect}
            >
              {inspect
                ? "Hide details"
                : trace.path === "vector"
                  ? "View memory search"
                  : "View details"}
            </button>
          </div>
        )}
        {inspect && trace && (
          <div className="inline-inspector">
            <RoutingPanel trace={trace} busy={Boolean(turn.pending)} />
          </div>
        )}
      </div>
    </article>
  );
}
