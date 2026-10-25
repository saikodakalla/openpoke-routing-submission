"""Read-only database browser. Identifiers come only from SQLite's own schema.

No SQL supplied by the browser is executed; values are always bound parameters.
FTS shadow tables are implementation details, not application records.
"""

from contextlib import contextmanager
import sqlite3


class RegistryInspector:
    def __init__(self, store):
        self.path = store.path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def quote(value):
        return '"' + value.replace('"', '""') + '"'

    def schema(self):
        with self.connect() as db:
            tables = []
            for entry in db.execute("PRAGMA table_list"):
                name = entry["name"]
                if entry["schema"] != "main" or entry["type"] == "shadow" or name.startswith("sqlite_"):
                    continue
                q = self.quote(name)
                definition = db.execute(
                    "SELECT sql FROM sqlite_master WHERE type=? AND name=?", ("table", name)
                ).fetchone()
                tables.append(
                    {
                        "name": name,
                        "columns": [dict(r) for r in db.execute(f"PRAGMA table_info({q})")],
                        "foreign_keys": [dict(r) for r in db.execute(f"PRAGMA foreign_key_list({q})")],
                        "indexes": [dict(r) for r in db.execute(f"PRAGMA index_list({q})")],
                        "count": db.execute(f"SELECT count(*) FROM {q}").fetchone()[0],
                        "sql": definition[0] if definition else "",
                    }
                )
            return {
                "tables": sorted(tables, key=lambda t: t["name"]),
                "read_only": True,
                "authority": "SQLite records determine task ownership. Chroma is a rebuildable search index.",
            }

    def rows(self, table, offset=0, limit=25, column=None, value=None):
        tables = {t["name"]: t for t in self.schema()["tables"]}
        if table not in tables:
            raise ValueError("Unknown application table")
        columns = tables[table]["columns"]
        if column and column not in {c["name"] for c in columns}:
            raise ValueError("Unknown column")
        q = self.quote(table)
        where = f" WHERE {self.quote(column)}=?" if column else ""
        args = (value,) if column else ()
        order = ",".join(self.quote(c["name"]) for c in sorted(columns, key=lambda c: c["pk"]) if c["pk"])
        if not order:
            order = "rowid"
        with self.connect() as db:
            total = db.execute(f"SELECT count(*) FROM {q}{where}", args).fetchone()[0]
            rows = [
                dict(r)
                for r in db.execute(
                    f"SELECT * FROM {q}{where} ORDER BY {order} LIMIT ? OFFSET ?", (*args, limit, offset)
                )
            ]
        return {
            "table": table,
            "columns": columns,
            "foreign_keys": tables[table]["foreign_keys"],
            "rows": rows,
            "offset": offset,
            "limit": limit,
            "total": total,
            "read_only": True,
        }
