"""Composition root used by the original FastAPI chat endpoint and CLI."""

import asyncio
import json
from functools import lru_cache

from .activity import ActivityRecorder, _current, note
from .index import TaskIndex
from .providers import CachedEmbeddings, FixtureEmbeddings, OpenRouter
from .router import Router
from .settings import RoutingSettings
from .store import Store


class RoutingService:
    def __init__(self, settings=None):
        self.settings = settings or RoutingSettings.from_env()
        self.store = Store(self.settings.data_dir / "registry.sqlite3")
        self.provider = OpenRouter(self.store, self.settings) if self.settings.mode == "live" else None
        embeddings = self.provider or FixtureEmbeddings(self.settings.dimension)
        self.embeddings = CachedEmbeddings(self.store, embeddings)
        self.index = TaskIndex(self.store, self.embeddings, self.settings.data_dir / "chroma")
        self.router = Router(self.store, self.index, self.settings, self.provider)
        if not self.settings.execution_url:
            from integration.openpoke_host import Dispatcher

            self.dispatcher = Dispatcher(self.store, self.settings, self.provider)
        else:
            from .bridge import OpenPokeDispatcher

            self.dispatcher = OpenPokeDispatcher(self.store, self.settings)

    def trace_view(self, trace):
        """Keep historical outcome snapshots, but hydrate current actionable draft state."""
        view = dict(trace)
        run = self.store.rows("SELECT status FROM routing_runs WHERE id=?", (trace["request_id"],))
        view["routing_status"] = run[0]["status"] if run else trace["decision"]
        view["current_drafts"] = self.store.rows(
            "SELECT * FROM drafts WHERE request_id=? OR approved_by=?",
            (trace["request_id"], trace["request_id"]),
        )
        view["current_orders"] = self.store.rows(
            "SELECT r.*,m.name merchant FROM order_requests r JOIN merchants m ON r.merchant_id=m.id WHERE request_id=? OR approved_by=?",
            (trace["request_id"], trace["request_id"]),
        )
        view["activity"] = self.store.rows(
            "SELECT * FROM request_activity WHERE request_id=? ORDER BY id", (trace["request_id"],)
        )
        for event in view["activity"]:
            event["detail"] = json.loads(event["detail"]) if event["detail"] else None
        return view

    async def handle(self, request, fail=False, on_activity=None):
        token = _current.set(ActivityRecorder(self.store, request.request_id, on_activity))
        try:
            return await self._handle(request, fail=fail)
        except Exception:
            note("error", "The request could not be completed")
            raise
        finally:
            _current.reset(token)

    async def _handle(self, request, fail=False):
        trace = await asyncio.to_thread(self.router.route, request)
        trace = await self.dispatcher.execute(trace, fail=fail)
        # New/updated tasks become searchable without a manual offline CLI step.
        # In live mode this uses the same explicit provider budget; failures stay queued.
        if (
            trace.get("task_id")
            and self.index.count_existing()
            and self.store.rows(
                "SELECT 1 FROM index_state WHERE collection=? AND indexed_version<>pending_version LIMIT 1",
                (self.index.name,),
            )
        ):
            try:
                from .activity import step

                with step("index", "Updating task memory"):
                    await asyncio.to_thread(self.index.repair, request_id=request.request_id)
            except Exception as exc:
                trace["indexing_warning"] = f"Memory update queued for retry: {type(exc).__name__}"
        trace["usage"] = self.store.rows(
            "SELECT kind,model,tokens,cost_bound,usage,status,elapsed_ms FROM provider_calls WHERE request_id=?",
            (request.request_id,),
        )
        # Also persist blocked concurrent-execution outcomes without touching the active lease.
        with self.store.connect(write=True) as db:
            db.execute("UPDATE routing_runs SET trace=? WHERE id=?", (json.dumps(trace), request.request_id))
            if (
                trace["execution"]["status"] in {"blocked", "failed"}
                and not db.execute(
                    "SELECT 1 FROM messages WHERE request_id=? AND role='assistant'", (request.request_id,)
                ).fetchone()
            ):
                db.execute(
                    "INSERT INTO messages(request_id,conversation_id,role,content) VALUES(?,?,?,?)",
                    (request.request_id, request.conversation_id, "assistant", trace["response"]),
                )
        return trace


@lru_cache(maxsize=1)
def get_routing_service():
    return RoutingService()
