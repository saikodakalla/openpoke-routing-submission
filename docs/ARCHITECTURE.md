# Architecture and interview guide

The durable object is a **task**, not an agent name. A task has a stable ID and a
foreign key to its execution agent. Its contacts, threads, history, commitments and
actions remain linked to that task. The router finds and verifies the task first;
the saved ownership link determines the execution agent.

## Process boundary and code ownership

`submission/` is the standalone application. Its FastAPI process performs lookup,
retrieval, verification and clarification. Its Next.js frontend displays conversation
and actual journaled operation events. `integration/host_server.py` runs in a separate
OpenPoke checkout and imports the original `ExecutionAgentRuntime`.

The bridge receives **only a persisted request ID** over authenticated localhost HTTP.
It reads the authorized trace from the same SQLite file, loads the saved task/owner,
rechecks its current version, and acquires an execution lease. The model cannot choose
an agent name or provide a different recipient/thread in tool arguments. The original
runtime executes with an injected task-scoped agent, provider and synthetic tools.

The supplied runtime patch adds that injection seam, tool observations and honest
failed-tool outcomes. It does not replace OpenPoke's execution loop. A verification
check runs against a pristine upstream archive plus only this patch. Running the
routing UI with an unadapted OpenPoke `/chat` endpoint alone is insufficient: the
host bridge is the explicit integration contract.

Shared SQLite makes the prototype small and reviewable. A distributed deployment
would need a separate authorization envelope/service API and managed storage rather
than a shared local file. A localhost token is not a multi-user authorization system.

## One request through the system

1. Assign a request ID and conversation ID. Resolve exact saved task/thread links,
   recent confirmed context, contact names, calendar phrases and persisted choices.
2. Consult SQLite ownership, metadata and FTS keyword matches. Apply the custom
   verifier. A sufficient owner bypasses language intake and semantic search.
3. Purchase preferences have an explicit SQL path: group completed receipts by
   merchant in the requested category. A tie asks a question using recorded names
   and counts. An answer refines the pending request and restarts lookup.
4. If still unresolved, live mode uses one bounded structured language-intake call
   to extract action/purpose/contact facts. Addresses must still be literal or match
   a uniquely identified saved contact. The model receives no full agent roster.
5. Only if SQLite evidence is insufficient, prepare the semantic index. On its first
   use, batch embed the current task cards and create a persistent Chroma collection.
   Later requests reuse it and repair pending versions. A cross-process file lock
   serializes cold builds. The query uses the same embedding model/dimension.
6. Retrieve ten task candidates; union them with SQL candidates. Reject stale vectors
   and verify current SQLite records. If unresolved, make one expansion to thirty.
   Do not repeatedly narrow until an arbitrary survivor wins.
7. Resume a supported owner, ask one factual distinction, or register confirmed new
   work atomically. No match by itself does not establish new work.
8. Persist the routing trace and ownership evidence. The bridge runs the selected
   OpenPoke agent with bounded task history. Tools persist actual draft/order/reminder
   state; assistant prose alone does not count as a successful action.
9. A draft or prepared order awaits user approval. Submit capabilities are hidden until
   an exact action ID is approved; tools also independently enforce that approval.
   Failures and interrupted outcomes remain visible and are not automatically replayed.

## What SQLite owns

| Tables | Role and important relationships |
|---|---|
| `agents`, `tasks` | Task PK → agent PK through `owner_id`; retain legacy execution name and history reference |
| `contacts`, `task_contacts`, `threads` | Explicit identities and verified thread ownership; junction table has a composite PK |
| `conversation_links`, `task_events` | Confirmed context and bounded supporting history |
| `routing_runs`, `messages`, `request_activity` | Persisted clarification, original/resolved requests, candidate evidence, results and actual stage events |
| `merchants`, `orders`, `order_requests` | Merchant/task mapping, completed/cancelled receipts, prepared/submitted synthetic baskets and exact approvals |
| `executions`, `drafts`, `commitments` | Execution leases, observable actions and durable reminders independent of task activity |
| `index_collections`, `index_state`, `embedding_cache` | Model namespace, durable version outbox and reusable vectors |
| `provider_calls` | Before-call budget reservations, attempt status, usage and latency |
| `tasks_fts` | SQLite FTS5 index synchronized by triggers |

WAL and foreign keys are enabled. Short `BEGIN IMMEDIATE` transactions protect
registration, duplicate keys and action authorization. A partial unique index allows
only one running execution per task and one pending clarification per conversation.
Per-conversation file locks serialize clarification updates across processes.

The UI reads the actual SQLite schema with PRAGMA metadata, including composite PK
positions, FK targets, indexes and CREATE statements. The read-only browser accepts
only schema-allowlisted table/column identifiers and bound values. It exposes no SQL
console. Rows are paginated and long JSON values expand. FK cells navigate to exact
referenced records. `task_events.request_id` and `request_activity.request_id` are
correlation fields rather than FKs because events may precede the final routing row.
JSON is stored as TEXT. SQLite ordinary TEXT PKs have SQLite's rowid-table nullability
semantics; application creation paths always generate non-null IDs.

## Embedding factors you can defend

| Factor | Actual implementation and reason |
|---|---|
| Embedded content | Exact task `title + newline + summary`. Compact task-sized cards, not entire mailboxes or execution logs. Names can appear naturally in prose; relational links remain authoritative. |
| Query content | The resolved request text, including a clarification answer when present. Same model as task cards. |
| Model | Live default `openai/text-embedding-3-small` through OpenRouter; configurable server-side. No hidden Chroma embedding function. |
| Dimensions | 1536 live, 256 offline fixture. Dimensional coordinates are learned features in live mode, not named axes like “Alice” or “Hawaii.” |
| Offline mode | Deterministic signed word-feature hashing. It validates persistence and control flow, not semantic accuracy. It has its own collection. |
| Unit and chunking | One card per durable task. This dataset needs no overlapping document chunks. Long histories stay outside embedding cards and are available to execution separately. |
| Similarity | Cosine similarity = dot product divided by the two vector lengths. Chroma uses cosine distance; the reported score is `1 - distance`. Higher similarity suggests relevance, not ownership. |
| Search index | Local persistent Chroma using its HNSW configuration with cosine space. Approximate neighbors are evaluated empirically; a bounded shortlist is not a claim of constant total search cost. |
| Candidate count | Initial ten; at most one expansion to thirty. SQL candidates are retained rather than eliminated to manufacture certainty. |
| Metadata | Identity, purpose, dates, state, owner and current version live in SQLite. Default vector search is not narrowly filtered; verification checks these facts afterward to protect recall. The index API supports explicit `where` constraints when appropriate. |
| Subject gate | A non-boilerplate/non-contact-name keyword overlap or live cosine ≥0.60 supports the subject. This gate caused four conservative misses in the current evaluation. |
| Cache | SHA-256 of exact content, model and dimension. Changes to text or model cannot silently reuse incompatible vectors. |
| Collection namespace | Hash of model, dimension and summary-version identifier; explicit externally supplied vectors, never a default model download. |
| Versioning | SQL update → pending version in the same transaction; Chroma upsert → acknowledge the version actually written. Deleted tasks and stale owner/version candidates are excluded. |
| Failure recovery | SQLite and Chroma have no shared atomic transaction. Interrupted upserts are safely replayed. CLI repair/rebuild is available; a missing index is rebuilt when semantic fallback next needs it. |
| Lazy work | Starting chat, reading status/schema/rows and opening an empty vector view do not create Chroma or call an embedding provider. First complex lookup pays corpus-build cost once. |
| Projection | PCA over actual current stored vectors; selected request uses its cached query vector in the same basis. Explained variance is shown. Two-dimensional distance is not the routing score or proof of ownership. |
| Privacy and cost | In live mode task-card/query text goes to the configured embedding provider. Keys remain backend-only. Every attempt has timeout, bounded retries and a persistent call/token/cost reservation. |

No separate LLM decides every candidate, no model is trained here, and there is no
custom vector database. The custom component is the small deterministic verifier.

## Candidate verifier

`task_router/verifier.py` is independent of language-model calls. For every candidate,
it returns current metadata, evidence, conflicts and these transparent score terms:

| Evidence | Weight |
|---|---:|
| Explicit task/thread ownership | +20 |
| Matching contact | +3 |
| Compatible purpose | +2 |
| Matching explicit date | +3 |
| Keyword overlap | `2 × overlapping request tokens / request tokens` |
| Semantic similarity | `1.5 × max(0, cosine)` |
| Supporting bounded history | +0.5 |
| Previously failed task state | −0.5 |

Hard contact/date/purpose conflicts veto reuse. Missing fields remain unknown. A
candidate also needs an ownership pattern: explicit linkage; contact plus date;
contact plus purpose and subject support; or date plus purpose and supporting history.
Then its score must be at least **5.0** and exceed the next non-conflicting candidate
by **1.25**. Scores are evidence weights, not calibrated probabilities. Shared name,
recency or semantic similarity alone cannot establish ownership.

The inspector exposes all four checks: compatible metadata, ownership evidence,
score threshold and ambiguity margin, plus rejected conflicts, score components and
actual cosine. A stage label “Complete” only means a computation ended. It does not
replace those checks or imply an accepted match.

## Why this design helps, and what it costs

- A verified thread/ownership link uses indexed relational evidence rather than a
  large roster prompt. Identity cannot depend on an invented agent display name.
- Cheap structured facts and keywords run before semantic work. Preference counts
  are SQL queries; embeddings would not reliably count receipts or resolve a tie.
- Semantic retrieval adds paraphrase recall, while a separate verifier can abstain
  when ownership is weak. A high cosine is not permission to act for another person.
- Persisted clarifications and action IDs survive restarts. Idempotency and leases
  protect against duplicate execution and uncontrolled replay after disconnects.
- The UI presents real events and inspectable records, making the decision defensible
  without showing private model reasoning or fabricated thinking animations.

Costs include an initial corpus embedding/index build, two-store recovery, an
explicit host integration patch, and conservative clarification. At 100 tasks this is
small enough to inspect. At much larger scale, use richer independently confirmed
ownership events, calibrated subject evidence, summary maintenance, observability and
retrieval/load testing. Benchmarking must include cold indexing, warm queries, token
usage and the full-roster baseline; a bounded prompt is not constant total work.

## What the measurements actually establish

See RESULTS.md. The current sample has strong retrieval and conservative verification:
18/22 correct decisions, 9/9 correct accepted reuses, zero observed wrong reuses, and
5/5 correct semantic shortlists. Four paraphrases were unnecessarily clarified because
their subject cosine did not reach 0.60. These are small conditional synthetic metrics,
not a claim of production accuracy. A successful live walkthrough separately verifies
natural intake, real upstream execution and actual synthetic action state.

The next useful experiment is a larger independently authored set with same-person,
same-purpose collisions and genuine negative pairs. Tune subject evidence on a new
development split, freeze it, then test an untouched set. Lowering the threshold after
seeing these held-out misses would invalidate their role as held-out evaluation.
