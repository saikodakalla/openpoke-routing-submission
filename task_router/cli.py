"""All live calls require a visibly separate command and persistent budget limits."""

import argparse
import asyncio
import json
import os

from .dataset import seed, seed_showcase
from .router import Request
from .service import RoutingService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "setup",
            "showcase",
            "doctor",
            "seed",
            "index",
            "rebuild",
            "repair",
            "status",
            "live-smoke",
            "live-setup",
            "migrate-legacy",
        ],
    )
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--text", default="Draft a follow-up in thread-0001")
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=20000)
    parser.add_argument("--max-cost", type=float, default=0.10)
    args = parser.parse_args()
    if args.command in {"live-smoke", "live-setup"}:
        os.environ.update(
            OPENPOKE_MODE="live",
            OPENPOKE_ALLOW_LIVE="1",
            OPENPOKE_MAX_CALLS=str(args.max_calls),
            OPENPOKE_MAX_TOKENS=str(args.max_tokens),
            OPENPOKE_MAX_COST_USD=str(args.max_cost),
        )
    service = RoutingService()
    if service.settings.mode == "live" and args.command in {"index", "rebuild", "repair"}:
        if not service.settings.allow_live:
            parser.error(
                "Live indexing is paid. Set OPENPOKE_ALLOW_LIVE=1 and explicit OPENPOKE_MAX_* limits."
            )
    if args.command == "live-setup":
        if not os.getenv("OPENROUTER_API_KEY"):
            parser.error(
                "Add OPENROUTER_API_KEY to the project .env before live setup. No paid calls were made."
            )
        if not service.store.rows("SELECT 1 FROM tasks LIMIT 1"):
            seed(service.store, args.size)
        result = {
            "indexed": 0,
            "indexing": "deferred until semantic search",
            "collection": service.index.name,
            "database": str(service.store.path.resolve()),
            "mode": "live",
        }
    elif args.command == "showcase":
        result = seed_showcase(service.store, args.size)
        service.index.schedule()
    elif args.command == "setup":
        if service.settings.mode != "offline":
            parser.error(
                "Setup initializes offline storage only. Use explicit bounded live indexing after adding a key."
            )
        if not service.store.rows("SELECT 1 FROM tasks LIMIT 1"):
            seed(service.store, args.size)
        service.index.schedule()
        repaired = 0
        result = {
            "database": str(service.store.path.resolve()),
            "sqlite_integrity": service.store.rows("PRAGMA integrity_check"),
            "foreign_key_errors": service.store.rows("PRAGMA foreign_key_check"),
            "indexed": repaired,
            "vectors": service.index.count_existing(),
            "mode": service.settings.mode,
        }
    elif args.command == "doctor":
        result = {
            "database": str(service.store.path.resolve()),
            "sqlite_integrity": service.store.rows("PRAGMA integrity_check"),
            "foreign_key_errors": service.store.rows("PRAGMA foreign_key_check"),
            "mode": service.settings.mode,
            "openrouter_key_configured": bool(os.getenv("OPENROUTER_API_KEY")),
            "live_calls_enabled": service.settings.mode == "live" and service.settings.allow_live,
            "embedding_model": service.embeddings.model,
            "dimension": service.embeddings.dimension,
            "vectors": service.index.count_existing(),
            "pending_index_updates": service.store.rows(
                "SELECT count(*) n FROM index_state WHERE collection=? AND indexed_version<>pending_version",
                (service.index.name,),
            )[0]["n"],
        }
    elif args.command == "seed":
        result = seed(service.store, args.size)
    elif args.command in {"index", "rebuild", "repair"}:
        service.index.schedule(rebuild=args.command == "rebuild")
        result = {"indexed": service.index.repair(), "collection": service.index.name}
    elif args.command == "live-smoke":
        result = asyncio.run(service.handle(Request(args.text)))
    elif args.command == "migrate-legacy":
        from server.services.execution import get_agent_roster
        from .store import uid

        count = 0
        with service.store.connect(write=True) as db:
            for name in get_agent_roster().get_agents():
                owner, task_id = uid("agent"), uid("task")
                if db.execute("SELECT 1 FROM agents WHERE legacy_name=?", (name,)).fetchone():
                    continue
                db.execute(
                    "INSERT INTO agents(id,legacy_name,history_ref) VALUES(?,?,?)",
                    (owner, name, "legacy-log:" + name),
                )
                db.execute(
                    "INSERT INTO tasks(id,owner_id,title,summary,state) VALUES(?,?,?,?,'dormant')",
                    (
                        task_id,
                        owner,
                        name,
                        "Imported legacy agent; ownership links need confirmation: " + name,
                    ),
                )
                count += 1
        result = {
            "imported": count,
            "note": "Original logs/triggers preserved. Confirm task relationships before semantic reuse.",
        }
    else:
        result = {
            "tasks": service.store.rows("SELECT count(*) n FROM tasks")[0]["n"],
            "vectors": service.index.count_existing(),
            "pending": service.store.rows("SELECT * FROM index_state WHERE indexed_version<>pending_version"),
            "collection": service.index.name,
            "mode": service.settings.mode,
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
