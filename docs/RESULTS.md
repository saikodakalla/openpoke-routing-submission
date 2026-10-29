# Measured results and limits

These results use `daily-life-showcase-v1`: **100 task records**, seed 27, linked
agents/contacts/threads and synthetic histories. The purchase seed contains two
completed orders per merchant plus one cancelled order per merchant. Cancelled
orders do not count toward a preference.

The evaluator's expected task/decision labels live in `evaluation/`, never in the
runtime router. Three development requests were run first. Verifier settings stayed
unchanged: score threshold 5.0, margin 1.25, subject cosine gate 0.60, shortlist 10,
one expansion to 30. The later 22-case evaluation spans different task families,
ambiguous identities, ambiguous dates, unowned requests and six extra semantic or
conflicting-identity probes. This is a small authored exploratory suite, not a
pre-registered external benchmark. No setting was tuned on its results.

## Retrieval and verification

Real provider: OpenRouter, model `openai/text-embedding-3-small`, **1536 dimensions**.
The evaluator supplies resolved contact/purpose context where a case specifies it,
and uses deterministic intake rules rather than an execution-model loop. These
numbers measure retrieval and verification conditional on that context. They do
not measure open-ended language understanding or email quality.

| Measure | Observed result | Denominator |
|---|---:|---:|
| Correct task/owner and routing decision | **18/22 = 81.8%** | All later evaluation cases |
| Correct accepted reuses / verifier acceptance precision | **9/9 = 100% observed** | Accepted existing owners |
| Wrong reuse | **0/22** | All requests |
| Initial semantic retrieval recall @10 | **5/5** | Vector-route cases with a known correct owner |
| Clarification rate | **13/22 = 59.1%** | All requests |
| Unnecessary clarification | **4** | Known-owner requests wrongly abstained |
| Development decision accuracy | **3/3** | Development examples only |

Small denominators matter. Nine correct accepts give an approximate 95% Wilson
precision interval of **70–100%**; five correct semantic shortlists give roughly
**57–100%**. Zero observed wrong reuses does not establish zero wrong-reuse risk.

Later evaluation median latency was about **396 ms**, p95 **694 ms** in the saved
mixed cache-state run. These are local conditional routing measurements, excluding
execution-model calls. The first development semantic request includes cold indexing
and must not be compared directly with warm requests. Per-case cache hits/misses,
index state, provider attempts and latency are saved in JSON/CSV. Cached replays
report their new-call count separately. The final fully cached replay had zero
new provider calls; its later-split median/p95 was about 294/376 ms. The cumulative isolated evaluation ledger
reported **$0.00005196** for actual embeddings through the saved expanded run;
this includes cold indexing and earlier development calls, not just the later split.
Do not substitute reservation estimates for these provider-reported charges.

## The four misses

All four correct tasks were retrieved. They were rejected by the independent
subject-support gate despite a high enough aggregate evidence score:

| Case | Correct task | Cosine | Score | Outcome |
|---|---|---:|---:|---|
| Oceanfront getaway | Coastal retreat | 0.4784 | 5.718 | Unnecessary clarification |
| Unpaid vendor bill | Orion invoice review | 0.4704 | 6.206 | Unnecessary clarification |
| Inclusive usability pitch | Atlas proposal | 0.4344 | 6.152 | Unnecessary clarification |
| German railway journey | Berlin train expedition | 0.5688 | 5.853 | Unnecessary clarification |

The gate requires either useful literal subject overlap or cosine ≥0.60. That
conservatism protects against broad contact/category matches becoming arbitrary
ownership. The next experiment should evaluate richer confirmed history/subject
signals on new development data, then an untouched larger set. Lowering the gate
until these four pass would overfit the reported evaluation.

## Actual live chat-to-OpenPoke walkthrough

A separate bounded functional run uses real chat intake and actual OpenPoke
execution through the localhost bridge. Success is checked against SQLite action
rows, agent identity, thread/recipient and stored orders, not assistant wording.

| User input | Path | Result |
|---|---|---|
| Write Alice Chen about the June Hawaii trip | SQLite/keyword | `task-0004`, owning agent, draft in `thread-0004` for Alice Chen |
| Order pizza from my usual spot | SQL receipt aggregation | Factual 2-vs-2 tie question, no dispatch |
| dominoes | Pending answer → direct owner | `task-0013`, Domino's saved basket prepared, awaiting approval |
| Email Noor about our upcoming oceanside holiday | Real embedding → Chroma → verifier | `task-0007`, owning agent, draft for Noor, no clarification |

Vector counts were **0 → 0 after the easy request → 0 after pizza → 100 after the
semantic request**. All created drafts/orders remained unapproved. No external
emails, payments or real orders occurred. The walkthrough's cumulative local ledger
contains 16 calls (13 chat, 3 embedding), including its initial failed attempt;
provider-reported cost was **$0.00235992**. This is a functional smoke, not a large
accuracy or cost comparison.

An initial live pizza run exposed an approval-capability issue: the model tried to
submit after preparing. The tool authorization rejected the attempt; the trace
correctly reported failure, and no order was submitted. That failure is retained in
`showcase-live-initial-failure.json`. The fix hides submit/send schemas until exact
approval exists, supplies task-specific instructions, and retains independent tool
checks. The final walkthrough passes. A regression verifies that unapproved submit
capabilities are absent from the model's tool list.

## Verification and evidence

- The standalone repository now collects **79 Python tests**: all **76** parent
  assessment cases and the original **3** standalone checks. The earlier wording
  of this document incorrectly attributed all 79 to the parent suite.
- Without OpenPoke: **49 passed, 30 explicitly marked integration tests skipped**.
  With pristine pinned upstream and the runtime patch: **78 passed, 1 skipped**;
  the remaining case checks legacy endpoints/guards in the modified parent app
  and separately passes with that app. Original names and assertions are retained.
  Run `.venv/bin/python -m pytest -q`; to include the original runtime, add
  `--openpoke-root=/absolute/path/to/openpoke`. The fixture copies the external
  server into a temporary directory and applies the submitted runtime patch there
  if needed, preserving the source checkout. Models are controlled fixtures; no
  API key is required. The legacy-parent-only case is explicitly marked
  `parent_app_integration`; the other runtime cases use `openpoke_integration`.
- Migration exposed a standalone SSE ordering defect: fast tool activity could be
  queued behind the final result. The stream publisher now immediately enqueues
  activity on its own loop while retaining thread-safe delivery from worker
  threads. The migrated stream test passes without changed assertions. Routing,
  verification, schema and embedding behaviour are unchanged.
- Browser suite: **18 passed** using the offline model fixture with real HTTP bridge,
  upstream runtime, SQLite and Chroma. This includes database/schema navigation,
  FK references, mobile overflow, activity, natural clarification and approvals.
- Production frontend build and TypeScript checks pass. The final source changes for
  persistent request selection and mode-specific embedding copy received source/type
  review; a later browser preview was declined and was not bypassed.
- Pristine upstream archive + only submitted runtime patch: verified existing-owner
  dispatch through HTTP with an actual persisted synthetic draft and no embeddings.

`results/` contains the measured JSON/CSV and functional traces. The parent repository
retains a larger historical offline baseline comparison and Manim explanation.
Fixture results do not establish real semantic accuracy, and those historical
artifacts are not relabeled as this new 100-record experiment. Larger repeated live
comparative benchmarks, production traffic, real mailbox execution and real merchant
integration remain outside the measured scope.
