# Conversational task assistant

A local chat interface for working with persistent tasks and their owning execution
agents. The main experience is an ordinary conversation. Operational activity appears
inline as the system actually checks SQLite, queries Chroma, verifies ownership and
calls execution tools. It does not expose private model reasoning.

No product branding, seeded task counters, scenario navigation, dashboard or persistent
technical sidebar. Benchmarks and synthetic scenarios remain developer fixtures outside
the chat experience. Tasks grow with use; the seed size is never a product limit.

Keep task evidence and the actual vector projection accessible on demand from the
relevant message. Preserve request correlation, clarification and draft approval.
The small mode label accurately discloses offline fixtures versus live model operation.
Audience: the author using and demonstrating an assistant through natural requests.

A top System view makes each request's architecture explorable without adding a
permanent sidebar. It shows real layer progress, direct-path bypasses, clarification
retry, and the actual stored/query-vector projection when Chroma is reached. Every
prompt is correlated by request ID and remains selectable after reload. Vectors
represent task summaries; authoritative ownership links select execution agents.

The assistant resolves recorded names, conversation references and calendar language
before asking the user anything. Internal database identifiers stay in inspection.
Natural answers persist across restart. A distinct requested email with an identified
recipient can establish its own task/owner and dispatch without a manual task choice.
Only unresolved real-world details become questions. Offline language rules remain
limited; general interpretation and fluent drafts require configured live models.

The system pane now includes a read-only database and schema browser. Selecting the
SQLite cylinder opens actual rows, columns, PK/FK relationships and reference links.
Vector inspection can open before search without creating an index. A 100-record
showcase is a developer seed, never a limit or a preset conversation mode.
