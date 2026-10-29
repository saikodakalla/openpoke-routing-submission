"""Independent chat/routing application; upstream runs behind a localhost bridge."""

import asyncio
from dataclasses import fields
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from .api import router
from .router import Request
from .service import get_routing_service
from .store import uid

app = FastAPI(title="Task routing")
app.include_router(router, prefix="/api/v1")
active = set()


class Chat(BaseModel):
    messages: list[dict] = Field(min_length=1)
    conversation_id: str = "demo"
    request_id: str | None = None
    task_id: str | None = None
    thread_id: str | None = None
    contact_email: str | None = None
    start_date: str | None = None
    purpose: str | None = None
    new_work: bool = False
    approval_draft_id: str | None = None
    approval_order_id: str | None = None

    def request(self):
        latest = next((m for m in reversed(self.messages) if m.get("role") == "user"), None)
        if not latest or not isinstance(latest.get("content"), str) or not latest["content"].strip():
            raise HTTPException(400, "Missing user message")
        payload = self.model_dump(exclude={"messages"})
        payload["request_id"] = self.request_id or uid("request")
        return Request(
            text=latest["content"].strip(),
            **{k: v for k, v in payload.items() if k in {f.name for f in fields(Request)}},
        )


@app.get("/api/v1/chat/history")
def history(conversation_id: str = "demo"):
    return {
        "messages": get_routing_service().store.rows(
            "SELECT id,request_id,role,content FROM messages WHERE conversation_id=? ORDER BY id",
            (conversation_id,),
        )
    }


@app.post("/api/v1/chat/send")
async def send(payload: Chat):
    return get_routing_service().trace_view(await get_routing_service().handle(payload.request()))


@app.post("/api/v1/chat/stream")
async def stream(payload: Chat):
    request = payload.request()

    async def events():
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def publish(event):
            item = ("activity", event)
            try:
                on_stream_loop = asyncio.get_running_loop() is loop
            except RuntimeError:
                on_stream_loop = False
            if on_stream_loop:
                # Fast tools can finish without yielding. Keep their activity
                # ahead of the terminal result instead of deferring it a turn.
                queue.put_nowait(item)
            else:
                loop.call_soon_threadsafe(queue.put_nowait, item)

        async def run():
            try:
                service = get_routing_service()
                trace = await service.handle(request, on_activity=publish)
                await queue.put(("result", service.trace_view(trace)))
            except Exception:
                await queue.put(
                    (
                        "error",
                        {
                            "request_id": request.request_id,
                            "message": "Request interrupted. Reload to inspect saved actions before retrying.",
                        },
                    )
                )

        task = asyncio.create_task(run())
        active.add(task)
        task.add_done_callback(active.discard)
        yield "event: ready\ndata: " + json.dumps({"request_id": request.request_id}) + "\n\n"
        while True:
            try:
                kind, data = await asyncio.wait_for(queue.get(), 15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield "event: " + kind + "\ndata: " + json.dumps(data) + "\n\n"
            if kind in {"result", "error"}:
                break

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
