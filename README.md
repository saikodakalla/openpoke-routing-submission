# Task routing submission

This folder contains the authored routing system and chat UI. It runs as its own
application and calls a separate local OpenPoke checkout for execution. The full
upstream repository is **not** part of this folder or the exported archive.

SQLite is built in. It owns task identity, agent ownership, contacts, threads,
clarifications, purchase history, actions and traces. Persistent Chroma is built in
for semantic search and is created only when a request needs that fallback. No
Supabase project is required for this local application.

## Run this folder separately

Requirements: Python 3.12, uv, Node 20+ and npm; an OpenPoke checkout at upstream
commit `5b5f635935a64ab37884c025d70abb0ed731c094`.

```bash
bash setup.sh
cp -n .env.example .env
bash run.sh /absolute/path/to/openpoke --offline
```

For real language understanding, embeddings and fluent drafts, put an OpenRouter
key in this folder's ignored `.env`, then use the explicit live command:

```bash
bash run.sh /absolute/path/to/openpoke --live
```

The launcher checks ports, applies the small reviewed runtime patch if needed,
seeds an empty registry, generates a local bridge credential and runs:

| Process | Address | Purpose |
|---|---|---|
| Chat | http://127.0.0.1:3001 | Plain chat and optional System view |
| Routing API | http://127.0.0.1:8003 | SQLite lookup, Chroma fallback, verification |
| OpenPoke host | http://127.0.0.1:8004 | Real upstream execution loop with scoped tools |

Both backend processes share the same absolute `OPENPOKE_DATA_DIR`. All processes
bind to localhost. The bridge accepts a persisted request ID and repeats ownership,
version and execution-lease checks. Stop the launcher with Ctrl+C. Existing data is
preserved. Different offline/live directories and model collections prevent mixing.

Live limits default to 100 cumulative calls, 200,000 reserved tokens and $1.00 in
conservative cost reservations per registry, across restarts. Override `OPENPOKE_MAX_*`
when launching. Reservations are not actual provider charges. Inspection never
makes model calls. All email and order operations remain synthetic; no external
mailbox, merchant payment or real order service is connected.

## Talk normally

There is no required scenario selector. These are useful ordinary requests for a
fresh 100-record seed; they are not hardcoded answers in the router:

1. **SQLite:** “Write Alice Chen about the June Hawaii trip”. Resolves the recorded
   task and creates a draft through OpenPoke without creating Chroma.
2. **Recorded preference:** “Order pizza from my usual spot”. Two completed receipts
   each for Domino's and Pizza Pizza produce a factual tie question. Reply “dominoes”
   or “Pizza Pizza”; the saved basket is prepared, awaiting approval. Cancelled
   receipts do not affect the count.
3. **Semantic:** “Email Noor about our upcoming oceanside holiday”. A real embedding
   retrieves the coastal retreat; contact/purpose/subject verification authorizes its
   owner without a clarification. Requires live embeddings; offline hashing only
   tests plumbing and does not promise to understand paraphrases.

Open **System view** to follow actual operation events. Click the SQLite cylinder
or Database/Schema to browse actual records, PK/FK columns and referenced rows.
Chroma/Vectors shows stored vectors, the selected request, retrieved candidates,
original cosine scores and an explicitly labeled PCA projection. Verification
shows the engine's individual checks, score components and winning margin.

A seed of 100 tasks is a reproducible starting point, not a task limit. Confirmed
new work can add records. `--size` supports other dataset sizes.

## Tests and evaluation

```bash
# Independent unit checks (no upstream checkout required).
.venv/bin/python -m pytest -q
# Seed another isolated showcase, without embeddings.
OPENPOKE_MODE=offline OPENPOKE_DATA_DIR=data/another .venv/bin/python -m task_router.cli showcase --size 100
# Inspect storage health without indexing or paid calls.
OPENPOKE_MODE=offline .venv/bin/python -m task_router.cli doctor
# Explicit pre-index/rebuild/repair are optional developer operations.
OPENPOKE_MODE=offline .venv/bin/python -m task_router.cli index
OPENPOKE_MODE=offline .venv/bin/python -m task_router.cli rebuild
OPENPOKE_MODE=offline .venv/bin/python -m task_router.cli repair
# Conditional retrieval/verifier evaluation. Default is offline hash fixtures.
.venv/bin/python -m evaluation.evaluate_showcase --data-dir data/evaluation-offline --output results/reproduced-offline.json
# Explicit bounded real embeddings; requires the key in backend .env.
.venv/bin/python -m evaluation.evaluate_showcase --live --data-dir data/evaluation-live --output results/reproduced-live.json --max-calls 40 --max-tokens 150000 --max-cost 0.50
```

Full upstream-runtime, API, concurrency, recovery, paid functional and browser
checks are documented in the [assessment repository](https://github.com/saikodakalla/openpoke-task-routing-assessment). Independent submission
tests also pass when this folder is copied outside the repository with no `server/`.
The external-host check extracts pristine upstream and applies only our small patch.

Read [Architecture and interview guide](docs/ARCHITECTURE.md),
[measured results and limits](docs/RESULTS.md) and the editable [schema](visuals/schema.mmd).
The original larger evaluation and Manim explanation remain in the parent repository;
they are historical artifacts and are not substituted for the new 100-record results.

## Layout and attribution

- `task_router/`: own API, storage, providers, lazy index, routing, verifier and bridge.
- `web/`: plain Next.js chat and on-demand inspectors.
- `integration/`: small OpenPoke host adapter, runtime patch and patch checker.
- `evaluation/`: labels and evaluator, separate from runtime inputs.
- `tests/`, `results/`, `visuals/`, `docs/`: reproducibility and interview evidence.

OpenPoke by Shlok Khemani is MIT licensed. Its original execution runtime is an
external dependency. The runtime patch is derived from that source and retains the
MIT license in this folder. Upstream: https://github.com/shlokkhemani/openpoke.
