"use client";
import { useEffect, useState } from "react";
type Column = {
  name: string;
  type: string;
  pk: number;
  notnull: number;
  dflt_value: string | null;
};
type ForeignKey = { from: string; table: string; to: string };
type Table = {
  name: string;
  count: number;
  columns: Column[];
  foreign_keys: ForeignKey[];
  sql: string;
};
type Rows = {
  rows: Record<string, unknown>[];
  total: number;
  columns: Column[];
  foreign_keys: ForeignKey[];
};
const display = (value: unknown) =>
  value == null
    ? "NULL"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);

export default function RegistryExplorer({
  initialMode = "rows",
}: {
  initialMode?: "rows" | "schema";
}) {
  const [tables, setTables] = useState<Table[]>([]);
  const [table, setTable] = useState("tasks");
  const [mode, setMode] = useState(initialMode);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<{
    column: string;
    value: string;
  } | null>(null);
  const [data, setData] = useState<Rows | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/routing/database/schema", { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            "Could not read the registry schema. Check the backend and retry.",
          );
        setTables((await r.json()).tables);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [reload]);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    const params = new URLSearchParams({ offset: String(offset), limit: "15" });
    if (filter) {
      params.set("column", filter.column);
      params.set("value", filter.value);
    }
    fetch(`/api/routing/database/rows/${encodeURIComponent(table)}?${params}`, {
      signal: controller.signal,
    })
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            "Could not read these records. Refresh the database view to retry.",
          );
        setData(await r.json());
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [table, offset, filter, reload]);
  const record = tables.find((t) => t.name === table);
  return (
    <section
      className="registry-explorer"
      aria-label="SQLite database inspector"
    >
      <div className="section-heading">
        <h3>SQLite registry</h3>
        <button onClick={() => setReload((r) => r + 1)}>Refresh</button>
      </div>
      <p className="small-note">
        Read-only application records. Primary keys identify rows; foreign keys
        link them to their owners and history.
      </p>
      <label className="request-picker">
        Table
        <select
          aria-label="Database table"
          value={table}
          onChange={(e) => {
            setTable(e.target.value);
            setOffset(0);
            setFilter(null);
          }}
        >
          {(tables.length ? tables : [{ name: "tasks", count: 0 }]).map((t) => (
            <option key={t.name} value={t.name}>
              {t.name} · {t.count} rows
            </option>
          ))}
        </select>
      </label>
      <div className="inspection-tabs" aria-label="Database views">
        <button aria-pressed={mode === "rows"} onClick={() => setMode("rows")}>
          Records
        </button>
        <button
          aria-pressed={mode === "schema"}
          onClick={() => setMode("schema")}
        >
          Schema & keys
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {filter && (
        <p className="db-filter">
          {filter.column} = {filter.value}{" "}
          <button
            onClick={() => {
              setFilter(null);
              setOffset(0);
            }}
          >
            Clear filter
          </button>
        </p>
      )}
      {mode === "schema" && record ? (
        <>
          <div
            className="database-scroll"
            tabIndex={0}
            aria-label="Schema columns"
          >
            <table className="retrieval-table">
              <caption>{table} columns</caption>
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Type</th>
                  <th>Keys / constraint</th>
                </tr>
              </thead>
              <tbody>
                {record.columns.map((c) => (
                  <tr key={c.name}>
                    <td>
                      <code>{c.name}</code>
                    </td>
                    <td>{c.type}</td>
                    <td>
                      {c.pk > 0 && <strong>PK {c.pk}</strong>}{" "}
                      {c.notnull ? "Required" : "Nullable"}
                      {record.foreign_keys
                        .filter((f) => f.from === c.name)
                        .map((f) => (
                          <p key={f.from}>
                            FK →{" "}
                            <button
                              className="db-reference"
                              onClick={() => {
                                setTable(f.table);
                                setFilter(null);
                                setOffset(0);
                              }}
                            >
                              {f.table}.{f.to}
                            </button>
                          </p>
                        ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>SQLite table definition</summary>
            <pre className="schema-source">{record.sql}</pre>
          </details>
        </>
      ) : mode === "rows" && data ? (
        <>
          <div
            className="database-scroll"
            tabIndex={0}
            aria-label="Database records"
          >
            <table className="retrieval-table database-table">
              <caption>
                {table} · {data.total} matching rows
              </caption>
              <thead>
                <tr>
                  {data.columns.map((c) => (
                    <th key={c.name} scope="col">
                      {c.name} {c.pk > 0 && <small>PK {c.pk}</small>}
                      {data.foreign_keys.some((f) => f.from === c.name) && (
                        <small>FK</small>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={i}>
                    {data.columns.map((c) => {
                      const fk = data.foreign_keys.find(
                        (f) => f.from === c.name,
                      );
                      const value = display(r[c.name]);
                      return (
                        <td key={c.name}>
                          {fk && r[c.name] != null ? (
                            <button
                              className="db-reference"
                              title={`Open ${fk.table}.${fk.to}`}
                              onClick={() => {
                                setTable(fk.table);
                                setFilter({ column: fk.to, value });
                                setOffset(0);
                              }}
                            >
                              {value} ↗
                            </button>
                          ) : value.length > 140 ? (
                            <details>
                              <summary>{value.slice(0, 100)}…</summary>
                              <pre>{value}</pre>
                            </details>
                          ) : (
                            value
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.rows.length && <p>No matching records in this table.</p>}
          <div className="database-pagination">
            <button
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 15))}
            >
              Previous
            </button>
            <span>
              {data.total ? offset + 1 : 0}–{Math.min(offset + 15, data.total)}{" "}
              of {data.total}
            </span>
            <button
              disabled={offset + 15 >= data.total}
              onClick={() => setOffset(offset + 15)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        !error && <p role="status">Reading SQLite…</p>
      )}
    </section>
  );
}
