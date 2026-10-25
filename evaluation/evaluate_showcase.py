"""Bounded 100-record retrieval/verifier evaluation; no execution model loop.

Resolved contact/purpose are explicit evaluation context, not gold task labels.
This measures retrieval and deterministic verification conditional on those facts.
Natural-language intake and actual tool execution are checked separately.
"""

import argparse
import csv
import hashlib
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_router.dataset import seed_showcase
from task_router.settings import RoutingSettings
from task_router.service import RoutingService
from task_router.router import Request, Router

# Development examples and held-out families are fixed before running evaluation.
CASES = [
    (
        "dev-coast",
        "development",
        "Email Noor about our upcoming oceanside holiday",
        "noor@example.test",
        "travel",
        "task-0007",
        "reuse",
    ),
    ("dev-ambiguous", "development", "Write Alice about the Hawaii trip", None, "travel", None, "clarify"),
    (
        "dev-sql",
        "development",
        "Write Alice Chen about the June Hawaii trip",
        None,
        None,
        "task-0004",
        "reuse",
    ),
    (
        "held-kyoto",
        "held-out",
        "Email Kenji about the fall gathering in Japan",
        "kenji@example.test",
        "travel",
        "task-0005",
        "reuse",
    ),
    (
        "held-invoice",
        "held-out",
        "Write Priya about settling the unpaid supplier bill",
        "priya@example.test",
        "finance",
        "task-0006",
        "reuse",
    ),
    (
        "held-design",
        "held-out",
        "Email Sam about inclusive design recommendations for the pitch",
        "sam@example.test",
        "project",
        "task-0008",
        "reuse",
    ),
    (
        "held-rail",
        "held-out",
        "Write Marta about the German railway journey and rooms",
        "marta@example.test",
        "travel",
        "task-0009",
        "reuse",
    ),
    (
        "held-receipts",
        "held-out",
        "Email Alice Chen about the Hawaii expense invoice",
        "alice.chen@example.test",
        "finance",
        "task-0010",
        "reuse",
    ),
    (
        "held-pizza",
        "held-out",
        "Write Alice Chen about pineapple catering for lunch",
        "alice.chen@example.test",
        "dining",
        "task-0002",
        "reuse",
    ),
    (
        "held-group",
        "held-out",
        "Email group@example.test about the Hawaii backup flights",
        "group@example.test",
        "travel",
        "task-0011",
        "reuse",
    ),
    (
        "held-two-dates",
        "held-out",
        "Email Alice Chen about our Hawaii vacation",
        "alice.chen@example.test",
        "travel",
        None,
        "clarify",
    ),
    (
        "held-two-people",
        "held-out",
        "Draft a Hawaii travel message for Alice",
        None,
        "travel",
        None,
        "clarify",
    ),
    ("held-unowned", "held-out", "Find the seaside escape and air tickets", None, None, None, "clarify"),
    (
        "held-unrelated",
        "held-out",
        "Continue that plan for something completely different",
        None,
        None,
        None,
        "clarify",
    ),
    (
        "held-easy-feb",
        "held-out",
        "Write Alice Morgan about the February Hawaii trip",
        None,
        None,
        "task-0003",
        "reuse",
    ),
    ("held-direct", "held-out", "Draft a short follow-up in thread-0001", None, None, "task-0001", "reuse"),
    ("held-purchase-tie", "held-out", "Order pizza from my usual spot", None, None, None, "clarify"),
    (
        "held-wrong-purpose",
        "held-out",
        "Continue the oceanside project for Noor",
        "noor@example.test",
        "project",
        None,
        "clarify",
    ),
    (
        "held-semantic-coast",
        "held-out",
        "Compose a note about our oceanfront getaway",
        "noor@example.test",
        "travel",
        "task-0007",
        "reuse",
    ),
    (
        "held-semantic-bill",
        "held-out",
        "Compose a note about settling the unpaid vendor bill",
        "priya@example.test",
        "finance",
        "task-0006",
        "reuse",
    ),
    (
        "held-semantic-pitch",
        "held-out",
        "Compose a note about the inclusive usability recommendations for our pitch",
        "sam@example.test",
        "project",
        "task-0008",
        "reuse",
    ),
    (
        "held-semantic-rail",
        "held-out",
        "Compose a note about the German railway journey and overnight rooms",
        "marta@example.test",
        "travel",
        "task-0009",
        "reuse",
    ),
    (
        "held-no-identity",
        "held-out",
        "Compose a note about our oceanfront getaway",
        None,
        "travel",
        None,
        "clarify",
    ),
    (
        "held-conflicting-identity",
        "held-out",
        "Compose a note about our oceanfront getaway",
        "sam@example.test",
        "travel",
        None,
        "clarify",
    ),
    (
        "held-missing",
        "held-out",
        "Continue the annual astronomy plan for zephyr@example.test",
        "zephyr@example.test",
        "project",
        None,
        "clarify",
    ),
]


def provenance():
    source = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=source, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit, dirty = None, None
    digest = hashlib.sha256()
    for p in sorted((source / "task_router").glob("*")):
        if p.suffix in {".py", ".sql"}:
            digest.update(p.name.encode())
            digest.update(p.read_bytes())
    return dict(source_commit=commit, source_dirty=dirty, runtime_source_sha256=digest.hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly permit paid real embeddings only")
    parser.add_argument("--split", choices=["development", "held-out", "all"], default="all")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--max-tokens", type=int, default=150000)
    parser.add_argument("--max-cost", type=float, default=0.50)
    args = parser.parse_args()
    base = RoutingSettings.from_env()
    settings = replace(
        base,
        data_dir=args.data_dir,
        mode="live" if args.live else "offline",
        allow_live=args.live,
        embedding_model="openai/text-embedding-3-small" if args.live else "fixture-hash-v1",
        dimension=1536 if args.live else 256,
        max_calls=args.max_calls,
        max_tokens=args.max_tokens,
        max_cost=args.max_cost,
    )
    service = RoutingService(settings)
    if not service.store.rows("SELECT 1 FROM tasks LIMIT 1"):
        seed_showcase(service.store)
    if service.store.rows("SELECT count(*) n FROM tasks")[0]["n"] != 100:
        parser.error("Use an isolated 100-record showcase directory")
    # Deliberately omit chat intake: these are conditional retrieval/verifier metrics.
    router = Router(service.store, service.index, settings, provider=None)
    vectors_before_easy = service.index.count_existing()
    simple = router.route(
        Request(
            "Write Alice Chen about the June Hawaii trip", conversation_id="eval-easy-" + str(time.time_ns())
        )
    )
    easy_vectors = service.index.count_existing()
    calls_before = service.store.rows("SELECT count(*) n FROM provider_calls")[0]["n"]
    results = []
    for label, split, text, email, purpose, expected, decision in CASES:
        if args.split != "all" and split != args.split:
            continue
        before_vectors = service.index.count_existing()
        hits, misses = service.embeddings.hits, service.embeddings.misses
        start = time.perf_counter()
        trace = router.route(
            Request(
                text,
                contact_email=email,
                purpose=purpose,
                conversation_id="eval-" + label + "-" + str(time.time_ns()),
            )
        )
        retrieved = trace.get("retrieved_ids", [])
        selected = trace.get("task_id")
        accepted = trace["decision"] == "reuse"
        results.append(
            dict(
                case=label,
                split=split,
                text=text,
                supplied_contact=email,
                supplied_purpose=purpose,
                expected_task=expected,
                expected_decision=decision,
                actual_task=selected,
                actual_decision=trace["decision"],
                path=trace["path"],
                owner_id=trace.get("owner_id"),
                expected_owner=service.store.task(expected)["owner_id"] if expected else None,
                index_was_cold=before_vectors == 0,
                index_prepare_ms=trace.get("timings_ms", {}).get("index_prepare", 0),
                indexed_records=trace.get("indexing", {}).get("updated_records", 0),
                cache_hits=service.embeddings.hits - hits,
                cache_misses=service.embeddings.misses - misses,
                correct=selected == expected
                and trace["decision"] == decision
                and (not expected or trace.get("owner_id") == service.store.task(expected)["owner_id"]),
                wrong_reuse=accepted and selected != expected,
                correct_reuse=accepted and selected == expected,
                accepted=accepted,
                recall_at_10=(expected in retrieved) if expected and trace["path"] == "vector" else None,
                retrieved_ids=retrieved,
                candidates=trace["candidates"],
                verification=trace.get("verification"),
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                routing_excluding_index_ms=round(
                    (time.perf_counter() - start) * 1000
                    - trace.get("timings_ms", {}).get("index_prepare", 0),
                    2,
                ),
                request_id=trace["request_id"],
            )
        )

    def aggregate(rows):
        n = len(rows)
        reused = sum(r["accepted"] for r in rows)
        recalled = [r["recall_at_10"] for r in rows if r["recall_at_10"] is not None]
        latency = sorted(r["latency_ms"] for r in rows)
        return dict(
            n=n,
            correct=sum(r["correct"] for r in rows),
            decision_accuracy=sum(r["correct"] for r in rows) / n if n else None,
            accepted_reuses=reused,
            wrong_reuses=sum(r["wrong_reuse"] for r in rows),
            reuse_precision=sum(r["correct_reuse"] for r in rows) / reused if reused else None,
            wrong_reuse_rate=sum(r["wrong_reuse"] for r in rows) / n if n else None,
            clarification_rate=sum(r["actual_decision"] == "clarify" for r in rows) / n if n else None,
            vector_recall_n=len(recalled),
            recall_at_10=sum(recalled) / len(recalled) if recalled else None,
            median_latency_ms=latency[len(latency) // 2] if n else None,
            p95_latency_ms=latency[min(n - 1, int(n * 0.95))] if n else None,
        )

    calls = service.store.rows("SELECT kind,model,status,usage,cost_bound,elapsed_ms FROM provider_calls")
    costs = [
        json.loads(r["usage"]).get("cost")
        for r in calls
        if r["usage"] and isinstance(json.loads(r["usage"]), dict)
    ]
    output = dict(
        scope="Conditional retrieval + deterministic verification with explicit contact/purpose context; not end-to-end language accuracy",
        mode="real OpenRouter embeddings" if args.live else "offline hash vectors; plumbing only",
        **provenance(),
        dataset="daily-life-showcase-v1",
        tasks=100,
        seed=27,
        model=service.embeddings.model,
        dimension=service.embeddings.dimension,
        configuration=dict(
            threshold=settings.threshold,
            margin=settings.margin,
            topic_similarity_min=settings.topic_similarity_min,
            shortlist=10,
            expansion=30,
        ),
        easy_sql=dict(
            correct=simple["task_id"] == "task-0004",
            vectors_before=vectors_before_easy,
            vectors_after=easy_vectors,
            created_vectors=easy_vectors - vectors_before_easy,
        ),
        results=results,
        aggregate={
            s: aggregate([r for r in results if r["split"] == s])
            for s in ["development", "held-out"]
            if any(r["split"] == s for r in results)
        },
        provider_calls=calls,
        provider_calls_this_run=len(calls) - calls_before,
        cost_scope="Persistent isolated evaluation ledger, including cold indexing and earlier cached runs. Per-case cache_hits/misses identify cache state.",
        cache_hits_this_run=sum(r["cache_hits"] for r in results),
        cache_misses_this_run=sum(r["cache_misses"] for r in results),
        provider_reported_cost=sum(c for c in costs if isinstance(c, (float, int))),
        cost_complete=len(costs) == len(calls),
        budgets=dict(calls=args.max_calls, tokens=args.max_tokens, cost=args.max_cost),
        failures=[r["case"] for r in results if not r["correct"]],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    with args.output.with_suffix(".csv").open("w") as f:
        cols = [
            "case",
            "split",
            "expected_task",
            "actual_task",
            "expected_decision",
            "actual_decision",
            "path",
            "correct",
            "wrong_reuse",
            "recall_at_10",
            "latency_ms",
        ]
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
    print(
        json.dumps(
            {
                k: output[k]
                for k in [
                    "mode",
                    "configuration",
                    "easy_sql",
                    "aggregate",
                    "provider_reported_cost",
                    "failures",
                ]
            },
            indent=2,
        )
    )
    for r in results:
        if r["case"] == "dev-coast":
            print(
                "Development coast scores:",
                [
                    (c["task_id"], c["similarity"], c["ownership_supported"])
                    for c in r["candidates"]
                    if c["task_id"] == "task-0007"
                ],
            )


if __name__ == "__main__":
    main()
