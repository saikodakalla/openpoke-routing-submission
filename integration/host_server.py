"""Run from an OpenPoke checkout: python -m submission.integration.host_server.

Only this process imports the real upstream ExecutionAgentRuntime. Both local
processes must point at exactly the same registry and share a backend-only token.
"""

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict
import uvicorn
from task_router.settings import RoutingSettings
from task_router.store import Store
from task_router.providers import OpenRouter
from task_router.activity import ActivityRecorder, _current
from .openpoke_host import Dispatcher

settings = RoutingSettings.from_env()
store = Store(settings.data_dir / "registry.sqlite3")
provider = OpenRouter(store, settings) if settings.mode == "live" else None
dispatcher = Dispatcher(store, settings, provider)
active = set()


@asynccontextmanager
async def lifespan(app):
    yield
    if active:
        await asyncio.gather(*active, return_exceptions=True)


app = FastAPI(title="Local OpenPoke execution bridge", lifespan=lifespan)


class Dispatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str


@app.get("/health")
def health():
    return {
        "runtime": "OpenPoke ExecutionAgentRuntime",
        "mode": settings.mode,
        "configured": bool(settings.bridge_token),
    }


@app.post("/execute")
async def execute(payload: Dispatch, authorization: str = Header(default="")):
    if not settings.bridge_token or not hmac.compare_digest(authorization, "Bearer " + settings.bridge_token):
        raise HTTPException(401, "Invalid local bridge credential")
    rows = store.rows("SELECT trace FROM routing_runs WHERE id=?", (payload.request_id,))
    if not rows:
        raise HTTPException(404, "No persisted authorized request in this registry")
    trace = json.loads(rows[0]["trace"])
    if trace["decision"] not in {"reuse", "create"} or not trace.get("owner_id"):
        raise HTTPException(409, "Request has no verified execution owner")

    async def run():
        token = _current.set(ActivityRecorder(store, payload.request_id))
        try:
            return await dispatcher.execute(trace)
        finally:
            _current.reset(token)

    task = asyncio.create_task(run())
    active.add(task)
    task.add_done_callback(active.discard)
    return await asyncio.shield(task)  # client disconnect never authorizes a replay


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8004)
