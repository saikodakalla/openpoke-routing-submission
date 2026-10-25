PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS agents (
 id TEXT PRIMARY KEY, legacy_name TEXT NOT NULL UNIQUE, history_ref TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES agents(id),
 title TEXT NOT NULL, summary TEXT NOT NULL, purpose TEXT,
 state TEXT NOT NULL CHECK(state IN ('active','dormant','completed','awaiting_approval','blocked','failed','deleted')),
 start_date TEXT, end_date TEXT, version INTEGER NOT NULL DEFAULT 1,
 dedupe_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner_id);
CREATE INDEX IF NOT EXISTS tasks_state_dates ON tasks(state,start_date,end_date);
CREATE TABLE IF NOT EXISTS contacts (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL);
CREATE INDEX IF NOT EXISTS contacts_name ON contacts(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS task_contacts (
 task_id TEXT REFERENCES tasks(id), contact_id TEXT REFERENCES contacts(id), PRIMARY KEY(task_id,contact_id)
);
CREATE INDEX IF NOT EXISTS contacts_tasks ON task_contacts(contact_id,task_id);
CREATE TABLE IF NOT EXISTS threads (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), subject TEXT NOT NULL,
 recipient TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS threads_task ON threads(task_id);
CREATE TABLE IF NOT EXISTS conversation_links (
 conversation_id TEXT NOT NULL, message_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
 evidence TEXT NOT NULL, PRIMARY KEY(conversation_id,message_id,task_id)
);
CREATE INDEX IF NOT EXISTS conversation_recent ON conversation_links(conversation_id,message_id DESC);
CREATE TABLE IF NOT EXISTS task_events (
 id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), request_id TEXT,
 kind TEXT NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS events_task ON task_events(task_id,id DESC);
CREATE TABLE IF NOT EXISTS routing_runs (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, original_request TEXT NOT NULL,
 resolved_request TEXT NOT NULL, status TEXT NOT NULL, trace TEXT NOT NULL,
 pending TEXT, parent_id TEXT REFERENCES routing_runs(id),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS runs_conversation ON routing_runs(conversation_id,created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS one_clarification ON routing_runs(conversation_id) WHERE status='clarify';
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY, request_id TEXT NOT NULL REFERENCES routing_runs(id), conversation_id TEXT NOT NULL,
 role TEXT NOT NULL, content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,id);
CREATE TABLE IF NOT EXISTS index_collections (
 name TEXT PRIMARY KEY, model TEXT NOT NULL, dimension INTEGER NOT NULL, summary_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS index_state (
 task_id TEXT NOT NULL REFERENCES tasks(id), collection TEXT NOT NULL,
 indexed_version INTEGER NOT NULL DEFAULT 0, pending_version INTEGER NOT NULL, error TEXT,
 PRIMARY KEY(task_id,collection)
);
CREATE TABLE IF NOT EXISTS embedding_cache (
 model TEXT NOT NULL, dimension INTEGER NOT NULL, content_hash TEXT NOT NULL,
 vector TEXT NOT NULL, PRIMARY KEY(model,dimension,content_hash)
);
CREATE TABLE IF NOT EXISTS executions (
 request_id TEXT PRIMARY KEY REFERENCES routing_runs(id), task_id TEXT NOT NULL REFERENCES tasks(id),
 owner_id TEXT NOT NULL REFERENCES agents(id), status TEXT NOT NULL, result TEXT,
 lease_until REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS task_running ON executions(task_id) WHERE status='running';
CREATE TABLE IF NOT EXISTS drafts (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), request_id TEXT NOT NULL,
 thread_id TEXT REFERENCES threads(id), recipient TEXT NOT NULL, body TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','sent')), approved_by TEXT
);
CREATE INDEX IF NOT EXISTS drafts_task ON drafts(task_id,status);
CREATE TABLE IF NOT EXISTS commitments (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), owner_id TEXT NOT NULL REFERENCES agents(id),
 due_at TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS commitments_due ON commitments(state,due_at);
CREATE TABLE IF NOT EXISTS provider_calls (
 id INTEGER PRIMARY KEY, request_id TEXT, kind TEXT NOT NULL, model TEXT NOT NULL,
 tokens INTEGER NOT NULL, cost_bound REAL NOT NULL, usage TEXT, status TEXT NOT NULL,
 elapsed_ms REAL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(id UNINDEXED,title,summary,content='tasks',content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS tasks_ai AFTER INSERT ON tasks BEGIN
 INSERT INTO tasks_fts(rowid,id,title,summary) VALUES(new.rowid,new.id,new.title,new.summary);
END;
CREATE TRIGGER IF NOT EXISTS tasks_ad AFTER DELETE ON tasks BEGIN
 INSERT INTO tasks_fts(tasks_fts,rowid,id,title,summary) VALUES('delete',old.rowid,old.id,old.title,old.summary);
END;
CREATE TRIGGER IF NOT EXISTS tasks_au AFTER UPDATE ON tasks BEGIN
 INSERT INTO tasks_fts(tasks_fts,rowid,id,title,summary) VALUES('delete',old.rowid,old.id,old.title,old.summary);
 INSERT INTO tasks_fts(rowid,id,title,summary) VALUES(new.rowid,new.id,new.title,new.summary);
 UPDATE index_state SET pending_version=new.version WHERE task_id=new.id;
END;

-- Progress starts before the final routing run is inserted, so this append-only
-- journal uses request identity without a premature foreign-key dependency.
CREATE TABLE IF NOT EXISTS request_activity (
 id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, operation_id TEXT NOT NULL,
 kind TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL,
 detail TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS activity_request ON request_activity(request_id,id);

-- Recorded purchase history supports frequency-based preferences without vectors.
CREATE TABLE IF NOT EXISTS merchants (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]',
 task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), items TEXT NOT NULL,
 ordered_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('completed','cancelled'))
);
CREATE INDEX IF NOT EXISTS orders_merchant ON orders(merchant_id,status,ordered_at DESC);
CREATE TABLE IF NOT EXISTS order_requests (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES routing_runs(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), merchant_id TEXT NOT NULL REFERENCES merchants(id),
 items TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('prepared','submitted')), approved_by TEXT
);
