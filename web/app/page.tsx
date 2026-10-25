"use client";
// THESIS: conversation is the product; actual operations provide a quiet explanation.
// OWN-WORLD: white canvas, charcoal text, soft gray user messages, neutral controls.
// STORY: type freely, watch real work, clarify or approve within the same conversation.
// FIRST VIEWPORT: a compact New chat action, centered greeting and multiline composer.
// FORM: one chat column; request-level evidence expands only on demand.
import { useCallback, useEffect, useRef, useState } from "react";
import { Composer } from "@/components/conversation/Composer";
import { MessageTurn, type Turn } from "@/components/conversation/MessageTurn";
import type { Activity, Trace } from "@/components/routing/types";
import dynamic from "next/dynamic";
const SystemView = dynamic(() =>
  import("@/components/routing/SystemView").then((m) => m.SystemView),
);
import { readChatStream } from "@/lib/chat-stream";

type Message = { request_id: string; role: string; content: string };
export default function Page() {
  const [conversation, setConversation] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [systemOpen, setSystemOpen] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const systemToggle = useRef<HTMLButtonElement>(null);
  const [announcement, setAnnouncement] = useState("");
  const inFlight = useRef(false);
  const scroll = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);

  useEffect(() => {
    let id = localStorage.getItem("assistant-conversation");
    if (!id) {
      id = `chat-${crypto.randomUUID()}`;
      localStorage.setItem("assistant-conversation", id);
    }
    setConversation(id);
    fetch("/api/routing/status")
      .then(async (response) => {
        if (response.ok) setMode((await response.json()).mode);
      })
      .catch(() => {});
  }, []);
  const load = useCallback(async (id: string, signal?: AbortSignal) => {
    const [history, records] = await Promise.all([
      fetch(`/api/chat/history?conversation_id=${encodeURIComponent(id)}`, {
        cache: "no-store",
        signal,
      }),
      fetch(`/api/routing/runs?conversation_id=${encodeURIComponent(id)}`, {
        cache: "no-store",
        signal,
      }),
    ]);
    if (!history.ok || !records.ok)
      throw new Error("Couldn’t load this chat. Check the server and reload.");
    const messages: Message[] = (await history.json()).messages;
    const traces: Trace[] = await records.json();
    const byRequest = new Map(traces.map((trace) => [trace.request_id, trace]));
    const grouped = new Map<string, Turn>();
    for (const message of messages) {
      const trace = byRequest.get(message.request_id);
      const turn = grouped.get(message.request_id) || {
        requestId: message.request_id,
        text: "",
        trace,
        activity: trace?.activity || [],
      };
      if (message.role === "user") turn.text = message.content;
      if (message.role === "assistant") turn.reply = message.content;
      grouped.set(message.request_id, turn);
    }
    if (!signal?.aborted) setTurns(Array.from(grouped.values()));
  }, []);
  useEffect(() => {
    if (!conversation) return;
    const controller = new AbortController();
    setLoading(true);
    load(conversation, controller.signal)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [conversation, load]);
  useEffect(() => {
    if (nearBottom.current && scroll.current)
      scroll.current.scrollTo({
        top: scroll.current.scrollHeight,
        behavior: "auto",
      });
  }, [turns]);

  const send = async (text: string, extra: Record<string, unknown> = {}) => {
    if (!text.trim() || inFlight.current || !conversation) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setAnnouncement("");
    setInput("");
    nearBottom.current = true;
    const requestId = `request-${crypto.randomUUID()}`;
    setSelectedRequest(requestId);
    setTurns((previous) => [
      ...previous,
      { requestId, text: text.trim(), activity: [], pending: true },
    ]);
    const updateActivity = (event: Activity) =>
      setTurns((previous) =>
        previous.map((turn) =>
          turn.requestId === requestId
            ? { ...turn, activity: [...turn.activity, event] }
            : turn,
        ),
      );
    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...extra,
          messages: [{ role: "user", content: text.trim() }],
          request_id: requestId,
          conversation_id: conversation,
        }),
      });
      const trace = await readChatStream(response, requestId, updateActivity);
      // Completion belongs to this request, never to an older assistant message.
      const currentDrafts = new Map(
        (trace.current_drafts || []).map((draft) => [draft.id, draft]),
      );
      setTurns((previous) =>
        previous.map((turn) => {
          if (turn.requestId === requestId)
            return {
              ...turn,
              trace,
              reply: trace.response,
              activity: trace.activity || turn.activity,
              pending: false,
            };
          if (!turn.trace || !currentDrafts.size) return turn;
          return {
            ...turn,
            trace: {
              ...turn.trace,
              current_drafts: (
                turn.trace.current_drafts ??
                turn.trace.execution.drafts ??
                []
              ).map((draft) => currentDrafts.get(draft.id) || draft),
            },
          };
        }),
      );
      setAnnouncement(trace.response);
      try {
        await load(conversation);
      } catch {
        // The action already succeeded. A failed read must never invite replaying it.
        setError(
          "Your request completed, but the chat could not refresh. Retry the refresh to update earlier messages.",
        );
      }
    } catch (failure) {
      const message =
        failure instanceof Error
          ? failure.message
          : "The request failed. Reload this chat before retrying.";
      setTurns((previous) =>
        previous.map((turn) =>
          turn.requestId === requestId
            ? { ...turn, pending: false, error: message }
            : turn,
        ),
      );
      setInput((current) => current || text);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  const newChat = () => {
    if (inFlight.current) return;
    const id = `chat-${crypto.randomUUID()}`;
    localStorage.setItem("assistant-conversation", id);
    setTurns([]);
    setSelectedRequest(null);
    setInput("");
    setError("");
    setConversation(id);
    nearBottom.current = true;
  };
  const empty = !turns.length;
  return (
    <main
      className={`chat-app ${empty ? "is-empty" : "has-messages"} ${systemOpen ? "system-open" : ""}`}
    >
      <p
        className="sr-only"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {announcement}
      </p>
      <header className="chat-toolbar">
        <button className="new-chat-button" onClick={newChat} disabled={busy}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-6M15.5 4.5l4 4M10 14l1-4L18 3a1.4 1.4 0 0 1 2 0l1 1a1.4 1.4 0 0 1 0 2l-7 7-4 1Z"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span>New chat</span>
        </button>
        <button
          ref={systemToggle}
          className="system-toggle"
          aria-expanded={systemOpen}
          aria-controls="request-system-view"
          onClick={() => setSystemOpen(!systemOpen)}
        >
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <rect x="7" y="2" width="6" height="4" rx="1" />
            <rect x="1" y="13" width="6" height="4" rx="1" />
            <rect x="13" y="13" width="6" height="4" rx="1" />
            <path d="M10 6v4H4v3m6-3h6v3" />
          </svg>
          System view{" "}
          {busy && (
            <span className="activity-spinner small" aria-hidden="true" />
          )}
        </button>
      </header>
      <div className="chat-workspace">
        <div className="chat-stage">
          <div
            className="conversation-scroll"
            ref={scroll}
            onScroll={() => {
              if (scroll.current)
                nearBottom.current =
                  scroll.current.scrollHeight -
                    scroll.current.scrollTop -
                    scroll.current.clientHeight <
                  100;
            }}
          >
            <section
              className="chat-column"
              aria-label="Conversation"
              aria-busy={busy || loading}
            >
              {empty && !loading && (
                <div className="chat-greeting">
                  <h1>How can I help?</h1>
                </div>
              )}
              {loading && (
                <p className="loading-chat" role="status">
                  Loading your chat…
                </p>
              )}
              {turns.map((turn) => (
                <MessageTurn
                  key={turn.requestId}
                  turn={turn}
                  busy={busy}
                  onSend={(text, extra) => void send(text, extra)}
                />
              ))}
              {error && (
                <p className="chat-error" role="alert">
                  {error}{" "}
                  <button
                    onClick={() => {
                      if (conversation)
                        void load(conversation)
                          .then(() => setError(""))
                          .catch(() => {});
                    }}
                  >
                    Try again
                  </button>
                </p>
              )}
            </section>
          </div>
          <Composer
            value={input}
            onChange={setInput}
            onSend={() => void send(input)}
            disabled={loading || !conversation}
            busy={busy}
            mode={mode}
          />
        </div>
        {systemOpen && (
          <div
            id="request-system-view"
            className="system-pane"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setSystemOpen(false);
                systemToggle.current?.focus();
              }
            }}
          >
            <SystemView
              turns={turns}
              selected={selectedRequest}
              onSelect={setSelectedRequest}
              onClose={() => {
                setSystemOpen(false);
                systemToggle.current?.focus();
              }}
            />
          </div>
        )}
      </div>
    </main>
  );
}
