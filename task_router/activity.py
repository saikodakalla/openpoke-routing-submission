"""Observable operations, not private model reasoning or simulated progress.

ContextVars follow asyncio.to_thread, so real SQLite, embedding and Chroma calls
can report their lifecycle without passing UI callbacks through the routing API.
Events are persisted before being delivered; reconnects can inspect the same record.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json

from uuid import uuid4


def uid(prefix):
    return f"{prefix}-{uuid4().hex[:16]}"


_current = ContextVar("request_activity", default=None)


class ActivityRecorder:
    def __init__(self, store, request_id, callback=None):
        self.store, self.request_id, self.callback = store, request_id, callback

    def emit(self, kind, label, status, detail=None, operation_id=None):
        operation_id = operation_id or uid("operation")
        with self.store.connect(write=True) as db:
            cursor = db.execute(
                "INSERT INTO request_activity(request_id,operation_id,kind,label,status,detail) VALUES(?,?,?,?,?,?)",
                (self.request_id, operation_id, kind, label, status, json.dumps(detail)),
            )
            event = dict(
                db.execute("SELECT * FROM request_activity WHERE id=?", (cursor.lastrowid,)).fetchone()
            )
        event["detail"] = detail
        if self.callback:
            self.callback(event)
        return operation_id


def begin(kind, label, detail=None):
    recorder = _current.get()
    return recorder.emit(kind, label, "started", detail) if recorder else None


def finish(operation_id, kind, label, detail=None, failed=False):
    recorder = _current.get()
    if recorder and operation_id:
        recorder.emit(kind, label, "failed" if failed else "completed", detail, operation_id)


def note(kind, label, detail=None):
    recorder = _current.get()
    if recorder:
        recorder.emit(kind, label, "completed", detail)


@contextmanager
def step(kind, label, detail=None):
    operation_id = begin(kind, label, detail)
    try:
        yield
    except Exception as exc:
        finish(operation_id, kind, label, {"error": str(exc)}, failed=True)
        raise
    else:
        finish(operation_id, kind, label, detail)


def traced(kind, label, detail=None):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with step(kind, label, detail):
                return function(*args, **kwargs)

        return wrapped

    return decorate


TOOL_LABELS = {
    "prepare_order": "Preparing your saved order",
    "submit_approved_order": "Submitting the approved synthetic order",
    "inspect_thread": "Reading the email thread",
    "create_draft": "Creating an email draft",
    "send_approved_draft": "Sending the approved draft",
    "create_commitment": "Saving a reminder",
    "read_original_history": "Reading task history",
}


def tool_event(status, name, detail=None, operation_id=None):
    label = TOOL_LABELS.get(name, name.replace("_", " "))
    if status == "started":
        return begin("tool", label, {"tool": name, "arguments": detail})
    finish(operation_id, "tool", label, {"tool": name, "result": detail}, failed=status == "failed")
