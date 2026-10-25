import { useId } from "react";
import type { Layer, LayerState } from "./system-state";

export function SystemFlow({
  states,
  hasRequest,
  vectorUsed,
  owner,
  clarified,
  answered,
  onInspect,
}: {
  onInspect?: (layer: "lookup" | "vector") => void;
  states: Record<Layer, LayerState>;
  hasRequest: boolean;
  vectorUsed: boolean;
  owner: boolean;
  clarified: boolean;
  answered: boolean;
}) {
  const marker = useId().replaceAll(":", "");
  const state = (layer: Layer) => (hasRequest ? states[layer] : "waiting");
  const node = (
    layer: Layer,
    x: number,
    y: number,
    width: number,
    title: string,
    subtitle: string,
    cylinder = false,
  ) => (
    <g
      className="flow-node"
      data-layer={layer}
      data-state={state(layer)}
      role={layer === "lookup" || layer === "vector" ? "button" : undefined}
      tabIndex={layer === "lookup" || layer === "vector" ? 0 : undefined}
      aria-label={
        layer === "lookup"
          ? "Open SQLite database"
          : layer === "vector"
            ? "Open vector database"
            : undefined
      }
      onClick={() => {
        if (layer === "lookup" || layer === "vector") onInspect?.(layer);
      }}
      onKeyDown={(event) => {
        if (
          (event.key === "Enter" || event.key === " ") &&
          (layer === "lookup" || layer === "vector")
        ) {
          event.preventDefault();
          onInspect?.(layer);
        }
      }}
    >
      {cylinder ? (
        <>
          <path
            d={`M${x} ${y + 12}V${y + 72}a${width / 2} 12 0 0 0 ${width} 0V${y + 12}`}
          />
          <ellipse cx={x + width / 2} cy={y + 12} rx={width / 2} ry="12" />
        </>
      ) : (
        <rect
          x={x}
          y={y}
          width={width}
          height="64"
          rx={layer === "request" ? 30 : 10}
        />
      )}
      <text x={x + width / 2} y={y + (cylinder ? 43 : 26)} textAnchor="middle">
        <tspan>{title}</tspan>
        <tspan className="flow-subtitle" x={x + width / 2} dy="19">
          {subtitle}
        </tspan>
      </text>
      <title>
        {title}: {state(layer)}
      </title>
    </g>
  );
  const edge = (name: string, d: string, traversed = false, dashed = false) => (
    <path
      data-edge={name}
      d={d}
      className={`flow-edge ${traversed ? "traversed" : ""} ${dashed ? "feedback" : ""}`}
      markerEnd={`url(#${marker}-${traversed ? "done" : "idle"})`}
    />
  );
  const decision = (cy: number, text: string) => (
    <g className="flow-gate">
      <path d={`M290 ${cy - 36}L380 ${cy}L290 ${cy + 36}L200 ${cy}Z`} />
      <text x="290" y={cy + 4} textAnchor="middle">
        {text}
      </text>
    </g>
  );
  return (
    <div className="system-diagram">
      <div className="compact-flow" aria-label="Request architecture">
        {(
          [
            ["request", "Your request", "Conversation + available context"],
            [
              "lookup",
              "SQLite · task registry",
              "Direct ownership, metadata + keywords",
            ],
            ["embedding", "Embed request", "Only if ownership is uncertain"],
            [
              "vector",
              "Chroma · vector database",
              "Retrieve task summary embeddings",
            ],
            [
              "verify",
              "Verify candidates",
              "Compare metadata, history + evidence",
            ],
          ] as const
        ).map(([layer, title, subtitle]) => (
          <div
            key={layer}
            className="compact-flow-node"
            data-state={state(layer)}
          >
            <div>
              {layer === "lookup" || layer === "vector" ? (
                <button
                  className="compact-inspect"
                  onClick={() => onInspect?.(layer)}
                >
                  {title} ↗
                </button>
              ) : (
                <strong>{title}</strong>
              )}
              <small>{subtitle}</small>
            </div>
            <span>
              {state(layer) === "skipped"
                ? "Bypassed"
                : state(layer) === "waiting"
                  ? "Not reached"
                  : state(layer) === "active"
                    ? "Running"
                    : state(layer) === "failed"
                      ? "Failed"
                      : state(layer) === "blocked"
                        ? "Blocked"
                        : "Complete"}
            </span>
          </div>
        ))}
        <p className="compact-branch">
          Owner supported → linked agent
          <br />
          Still uncertain → ask a clarification
        </p>
        <div className="compact-outcomes">
          {(
            [
              ["execution", "Execution agent", "Load history + run tools"],
              ["clarify", "Clarification", "Your answer → lookup again"],
            ] as const
          ).map(([layer, title, subtitle]) => (
            <div
              key={layer}
              className="compact-flow-node"
              data-state={state(layer)}
            >
              <div>
                <strong>{title}</strong>
                <small>{subtitle}</small>
              </div>
              <span>
                {state(layer) === "skipped"
                  ? "Bypassed"
                  : state(layer) === "waiting"
                    ? "Not reached"
                    : state(layer) === "active"
                      ? "Running"
                      : state(layer) === "failed"
                        ? "Failed"
                        : state(layer) === "blocked"
                          ? "Blocked"
                          : "Complete"}
              </span>
            </div>
          ))}
        </div>
        <p className="small-note">
          Confirmed ownership skips vector retrieval. Explicitly confirmed new
          work registers a new task and owner.
        </p>
      </div>
      <svg
        className="system-flow"
        viewBox="0 0 590 915"
        role="img"
        aria-label="Request flow: ownership lookup, vector fallback, verification, agent execution or clarification"
      >
        <defs>
          {["idle", "done"].map((tone) => (
            <marker
              key={tone}
              id={`${marker}-${tone}`}
              viewBox="0 0 12 12"
              refX="10"
              refY="6"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <path
                d="M1 1L11 6L1 11Z"
                fill={tone === "done" ? "#368165" : "#777777"}
              />
            </marker>
          ))}
        </defs>
        <rect
          className="flow-group"
          x="130"
          y="104"
          width="320"
          height="205"
          rx="14"
        />
        <rect
          className="flow-group"
          x="130"
          y="347"
          width="320"
          height="415"
          rx="14"
        />
        <text className="flow-caption" x="146" y="121">
          Direct ownership
        </text>
        {edge(
          "request-lookup",
          "M290 80V132",
          hasRequest && state("lookup") !== "waiting",
        )}
        {node(
          "request",
          150,
          16,
          280,
          "Your request",
          "Conversation + available context",
        )}
        {node(
          "lookup",
          145,
          136,
          290,
          "SQLite · task registry",
          "Resolve names, links + saved context",
          true,
        )}
        {edge(
          "lookup-decision",
          "M290 220V234",
          state("lookup") === "complete",
        )}
        {decision(270, "Owner found?")}
        {edge("direct-execution", "M200 270H80V820", owner && !vectorUsed)}
        <text className="flow-caption flow-edge-label" x="168" y="258">
          Yes
        </text>
        {edge(
          "fallback",
          "M290 306V360",
          state("embedding") === "active" || state("embedding") === "complete",
        )}
        <text className="flow-caption flow-edge-label" x="305" y="338">
          Uncertain
        </text>
        {node(
          "embedding",
          170,
          366,
          240,
          "Embed request",
          "Configured embedding model",
        )}
        {edge(
          "embedding-chroma",
          "M290 430V464",
          state("embedding") === "complete",
        )}
        {node(
          "vector",
          145,
          464,
          290,
          "Chroma · vector database",
          "Retrieve task summary embeddings",
          true,
        )}
        {edge("chroma-verify", "M290 548V586", state("vector") === "complete")}
        {node(
          "verify",
          145,
          586,
          290,
          "Verify candidates",
          "Compare metadata + relevant history",
        )}
        {edge(
          "verify-decision",
          "M290 650V684",
          state("verify") === "complete",
        )}
        {decision(720, "Owner resolved?")}
        {edge("verified-execution", "M200 720H190V820", owner && vectorUsed)}
        <text className="flow-caption flow-edge-label" x="148" y="706">
          Yes
        </text>
        {edge("clarification", "M380 720H442V820", clarified)}
        <text className="flow-caption flow-edge-label" x="453" y="782">
          Uncertain
        </text>
        {node(
          "execution",
          15,
          824,
          245,
          "Linked execution agent",
          "Load history + run tools",
        )}
        {node(
          "clarify",
          320,
          824,
          245,
          "Ask a natural question",
          "Only a missing real-world detail",
        )}
        {edge("answer-retry", "M565 856H580V178H435", answered, true)}
        <rect
          className="flow-feedback-label"
          x="466"
          y="390"
          width="103"
          height="47"
          rx="6"
        />
        <text className="flow-caption" x="516" y="408" textAnchor="middle">
          <tspan>Your answer</tspan>
          <tspan x="516" dy="16">
            retries lookup
          </tspan>
        </text>
        <text className="flow-caption" x="290" y="910" textAnchor="middle">
          Every arrow connects a specific decision to the next operation
        </text>
      </svg>
    </div>
  );
}
