"""Local HTTP execution port: send a persisted request ID, never an agent name.

The host reads the same registry and repeats owner/version/lease checks. Tool
activity is persisted by the host; polling forwards only newly recorded events.
"""

import asyncio
import json
from urllib.parse import urlparse
import httpx
from .activity import _current, step


class OpenPokeDispatcher:
    def __init__(self, store, settings, transport=None):
        self.store, self.settings, self.transport = store, settings, transport
        self.url = settings.execution_url or "http://127.0.0.1:8004"
        parsed = urlparse(self.url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("The prototype execution bridge must use localhost HTTP")

    async def execute(self, trace, fail=False):
        if trace["decision"] not in {"reuse", "create"}:
            return trace
        if not self.settings.bridge_token:
            return self.blocked(
                trace, "Configure OPENPOKE_BRIDGE_TOKEN and start the local OpenPoke host adapter."
            )
        recorder = _current.get()
        last_id = self.store.rows(
            "SELECT coalesce(max(id),0) n FROM request_activity WHERE request_id=?", (trace["request_id"],)
        )[0]["n"]

        async def forward_events():
            nonlocal last_id
            while True:
                await asyncio.sleep(0.12)
                rows = self.store.rows(
                    "SELECT * FROM request_activity WHERE request_id=? AND id>? ORDER BY id",
                    (trace["request_id"], last_id),
                )
                for row in rows:
                    last_id = row["id"]
                    row["detail"] = json.loads(row["detail"]) if row["detail"] else None
                    if recorder and recorder.callback:
                        recorder.callback(row)

        poll = asyncio.create_task(forward_events())
        try:
            with step("execution", "Running the owning OpenPoke agent", "Local OpenPoke execution host"):
                async with httpx.AsyncClient(
                    timeout=130, transport=self.transport, trust_env=False
                ) as client:
                    response = await client.post(
                        self.url.rstrip("/") + "/execute",
                        headers={"Authorization": "Bearer " + self.settings.bridge_token},
                        json={"request_id": trace["request_id"]},
                    )
                response.raise_for_status()
                result = response.json()
                if (
                    result.get("request_id") != trace["request_id"]
                    or result.get("task_id") != trace["task_id"]
                    or result.get("owner_id") != trace["owner_id"]
                ):
                    raise ValueError("Execution host returned a different request or owner")
                return result
        except Exception as exc:
            # A timeout does not prove cancellation. Never replay automatically.
            return self.blocked(
                trace,
                f"OpenPoke host unavailable or interrupted ({type(exc).__name__}). Inspect saved actions before retrying.",
            )
        finally:
            poll.cancel()
            try:
                await poll
            except asyncio.CancelledError:
                pass
            # Flush final events without creating duplicate journal entries.
            for row in self.store.rows(
                "SELECT * FROM request_activity WHERE request_id=? AND id>? ORDER BY id",
                (trace["request_id"], last_id),
            ):
                row["detail"] = json.loads(row["detail"]) if row["detail"] else None
                if recorder and recorder.callback:
                    recorder.callback(row)

    @staticmethod
    def blocked(trace, message):
        trace["execution"] = {"status": "blocked", "error": message}
        trace["response"] = message
        return trace
