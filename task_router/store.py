"""Authoritative records. Short BEGIN IMMEDIATE transactions protect decisions.

No transaction spans SQLite and Chroma. Index work is an explicitly repairable outbox.
"""

from .activity import traced
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def tokens(text):
    return set(re.findall(r"[a-z0-9@.]+", text.lower())) - {
        "the",
        "a",
        "to",
        "for",
        "with",
        "my",
        "please",
        "can",
        "you",
        "and",
        "of",
        "in",
        "it",
        "about",
    }


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(Path(__file__).with_name("schema.sql").read_text())

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, params=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, params)]

    def task(self, task_id):
        rows = self.rows(
            "SELECT t.*,a.legacy_name,a.history_ref FROM tasks t JOIN agents a ON a.id=t.owner_id "
            "WHERE t.id=?",
            (task_id,),
        )
        if not rows:
            return None
        task = rows[0]
        task["contacts"] = self.rows(
            "SELECT c.* FROM contacts c JOIN task_contacts tc ON c.id=tc.contact_id WHERE tc.task_id=?",
            (task_id,),
        )
        task["threads"] = self.rows("SELECT * FROM threads WHERE task_id=?", (task_id,))
        return task

    def history(self, task_id, limit=6):
        return self.rows(
            "SELECT kind,payload,request_id FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT ?",
            (task_id, limit),
        )

    def event(self, task_id, kind, payload, request_id=None, db=None):
        args = (task_id, request_id, kind, json.dumps(payload))
        if db is not None:
            db.execute("INSERT INTO task_events(task_id,request_id,kind,payload) VALUES(?,?,?,?)", args)
        else:
            with self.connect(write=True) as conn:
                conn.execute("INSERT INTO task_events(task_id,request_id,kind,payload) VALUES(?,?,?,?)", args)

    @traced("keyword", "Searching saved tasks", "SQLite · titles and summaries")
    def keyword(self, text, limit=10):
        words = sorted(tokens(text))[:40]
        if not words:
            return []
        query = " OR ".join('"' + w.replace('"', "") + '"' for w in words)
        return self.rows(
            "SELECT id AS task_id,bm25(tasks_fts) AS rank FROM tasks_fts WHERE tasks_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        )

    @traced("metadata", "Checking contacts and dates", "SQLite · task relationships")
    def metadata_candidates(self, request, limit=30):
        """Contacts and temporal constraints are indexed relational evidence.

        They expand recall but do not independently authorize dispatch. Return one
        overflow sentinel so a truncated ownership set can never manufacture certainty.
        """
        if request.contact_email:
            return self.rows(
                "SELECT tc.task_id FROM contacts c JOIN task_contacts tc ON tc.contact_id=c.id "
                "JOIN tasks t ON t.id=tc.task_id WHERE c.email=? AND t.state<>'deleted' LIMIT ?",
                (request.contact_email, limit + 1),
            )
        if request.start_date and request.purpose:
            return self.rows(
                "SELECT id AS task_id FROM tasks WHERE start_date=? AND purpose=? AND state<>'deleted' LIMIT ?",
                (request.start_date, request.purpose, limit + 1),
            )
        name_words = sorted(w for w in tokens(request.text) if w.isalpha() and len(w) > 2)[:30]
        if name_words:
            clauses = " OR ".join("(c.name=? COLLATE NOCASE OR c.name LIKE ?)" for _ in name_words)
            params = [v for word in name_words for v in (word, word + " %")]
            return self.rows(
                "SELECT DISTINCT tc.task_id FROM contacts c JOIN task_contacts tc ON tc.contact_id=c.id "
                "JOIN tasks t ON t.id=tc.task_id WHERE t.state<>'deleted' AND (" + clauses + ") LIMIT ?",
                (*params, limit + 1),
            )
        return []

    def update_summary(self, task_id, summary):
        with self.connect(write=True) as db:
            db.execute(
                "UPDATE tasks SET summary=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=?",
                (summary, task_id),
            )

    def establish(self, text, contact_email=None, purpose=None, start_date=None):
        """Stable duplicate key and owner creation are protected by the same transaction.

        This handles identical normalized requests. Fuzzy duplicates require clarification;
        a similarity threshold cannot provide a uniqueness constraint.
        """
        key = hashlib.sha256(
            json.dumps([sorted(tokens(text)), contact_email, purpose, start_date]).encode()
        ).hexdigest()
        with self.connect(write=True) as db:
            row = db.execute("SELECT id FROM tasks WHERE dedupe_key=?", (key,)).fetchone()
            if row:
                return row[0], False
            task_id, owner = uid("task"), uid("agent")
            name = f"Task {task_id}: {text[:65]}"
            db.execute(
                "INSERT INTO agents(id,legacy_name,history_ref) VALUES(?,?,?)",
                (owner, name, f"sqlite:task_events/{task_id}"),
            )
            db.execute(
                "INSERT INTO tasks(id,owner_id,title,summary,purpose,state,start_date,dedupe_key) "
                "VALUES(?,?,?,?,?,'active',?,?)",
                (task_id, owner, text[:120], text, purpose, start_date, key),
            )
            if contact_email:
                contact_id = uid("contact")
                db.execute(
                    "INSERT OR IGNORE INTO contacts(id,name,email) VALUES(?,?,?)",
                    (contact_id, contact_email.split("@")[0], contact_email),
                )
                contact_id = db.execute("SELECT id FROM contacts WHERE email=?", (contact_email,)).fetchone()[
                    0
                ]
                db.execute("INSERT INTO task_contacts VALUES(?,?)", (task_id, contact_id))
                db.execute(
                    "INSERT INTO threads(id,task_id,subject,recipient) VALUES(?,?,?,?)",
                    (uid("thread"), task_id, text[:120], contact_email),
                )
            db.execute(
                "INSERT INTO index_state(task_id,collection,pending_version) SELECT ?,name,1 FROM index_collections",
                (task_id,),
            )
            self.event(task_id, "ownership", {"owner_id": owner, "source": "confirmed new work"}, db=db)
        return task_id, True
