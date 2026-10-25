"""Read-only inspection plus an explicit isolated synthetic-demo reset."""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .dataset import SAMPLES, seed, seed_showcase
from .service import get_routing_service

router = APIRouter(prefix="/routing", tags=["routing"])


@router.get("/status")
def status():
    s = get_routing_service()
    return {
        "mode": s.settings.mode,
        "model": s.embeddings.model,
        "dimension": s.embeddings.dimension,
        "tasks": s.store.rows("SELECT count(*) AS n FROM tasks WHERE state<>'deleted'")[0]["n"],
        "vectors": s.index.count_existing(),
        "collection": s.index.name,
        "pending_index": s.store.rows(
            "SELECT count(*) n FROM index_state WHERE collection=? AND indexed_version<>pending_version",
            (s.index.name,),
        )[0]["n"],
        "live_enabled": s.settings.allow_live,
        "samples": SAMPLES,
    }


@router.get("/runs/{request_id}")
def run(request_id: str):
    rows = get_routing_service().store.rows("SELECT trace FROM routing_runs WHERE id=?", (request_id,))
    if not rows:
        raise HTTPException(404, "Unknown request")
    return get_routing_service().trace_view(json.loads(rows[0]["trace"]))


@router.get("/runs")
def runs(conversation_id: str = "demo"):
    return [
        get_routing_service().trace_view(json.loads(r["trace"]))
        for r in get_routing_service().store.rows(
            "SELECT trace FROM routing_runs WHERE conversation_id=? ORDER BY created_at DESC",
            (conversation_id,),
        )
    ]


@router.get("/vectors")
async def vectors(request_id: str | None = None):
    service = get_routing_service()
    if request_id and not service.store.rows(
        "SELECT 1 FROM request_activity WHERE request_id=? UNION SELECT 1 FROM routing_runs WHERE id=? LIMIT 1",
        (request_id, request_id),
    ):
        raise HTTPException(404, "Unknown request")
    return await asyncio.to_thread(service.index.projection, request_id=request_id)


@router.get("/tasks/{task_id}")
def task(task_id: str):
    s = get_routing_service()
    record = s.store.task(task_id)
    if not record:
        raise HTTPException(404, "Unknown task")
    return {
        "task": record,
        "history": s.store.history(task_id, 20),
        "commitments": s.store.rows("SELECT * FROM commitments WHERE task_id=?", (task_id,)),
    }


class Reset(BaseModel):
    confirm: str
    size: int = Field(default=100, ge=12, le=2000)


@router.post("/reset")
async def reset(payload: Reset):
    s = get_routing_service()
    if s.settings.mode != "offline" or payload.confirm != "RESET SYNTHETIC DEMO":
        raise HTTPException(403, "Reset is restricted to explicitly confirmed offline synthetic data")
    with s.store.connect(write=True) as db:
        if db.execute("SELECT 1 FROM executions WHERE status='running'").fetchone():
            raise HTTPException(409, "Wait for active executions before resetting")
        for table in (
            "order_requests",
            "orders",
            "merchants",
            "request_activity",
            "messages",
            "drafts",
            "executions",
            "conversation_links",
            "task_events",
            "commitments",
            "index_state",
            "task_contacts",
            "threads",
            "routing_runs",
            "tasks",
            "agents",
            "contacts",
            "provider_calls",
            "embedding_cache",
        ):
            db.execute(f"DELETE FROM {table}")
    collection = s.index._open()
    if collection is not None:
        ids = collection.get()["ids"]
        if ids:
            collection.delete(ids=ids)
    (seed_showcase if payload.size >= 14 else seed)(s.store, payload.size)
    s.index.schedule()
    return status()


@router.get("/database/schema")
def database_schema():
    from .inspection import RegistryInspector

    return RegistryInspector(get_routing_service().store).schema()


@router.get("/database/rows/{table}")
def database_rows(
    table: str, offset: int = 0, limit: int = 25, column: str | None = None, value: str | None = None
):
    from .inspection import RegistryInspector

    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Offset must be nonnegative and limit between 1 and 100")
    try:
        return RegistryInspector(get_routing_service().store).rows(table, offset, limit, column, value)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
