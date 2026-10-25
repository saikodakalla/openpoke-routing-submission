"use client";
import { useEffect, useRef } from "react";

export function Composer({
  value,
  onChange,
  onSend,
  disabled,
  busy,
  mode,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled: boolean;
  busy: boolean;
  mode: string | null;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (input.current) {
      input.current.style.height = "auto";
      input.current.style.height = `${Math.min(input.current.scrollHeight, 180)}px`;
    }
  }, [value]);
  return (
    <div className="composer-dock">
      <div className="composer-width">
        <form
          className="chat-composer"
          onSubmit={(e) => {
            e.preventDefault();
            if (!disabled && !busy && value.trim()) onSend();
          }}
        >
          <textarea
            ref={input}
            aria-label="Message"
            placeholder="Message…"
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                if (!disabled && !busy && value.trim()) onSend();
              }
            }}
          />
          <div className="composer-bottom">
            <span className="composer-hint">
              {busy
                ? "Working on your request"
                : "Shift + Enter for a new line"}
            </span>
            <button
              className="send-button"
              type="submit"
              disabled={disabled || busy || !value.trim()}
              aria-label="Send message"
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M12 19V5m-5 5 5-5 5 5"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </form>
        <p
          className="mode-note"
          title={
            mode === "offline"
              ? "Deterministic test responses and a synthetic inbox. Live model calls require backend configuration."
              : "Model calls use the configured backend provider. Email actions use the synthetic inbox."
          }
        >
          {mode === "offline"
            ? "Offline test mode · limited language understanding"
            : mode === "live"
              ? "Live model · synthetic inbox"
              : "Connecting…"}
        </p>
      </div>
    </div>
  );
}
