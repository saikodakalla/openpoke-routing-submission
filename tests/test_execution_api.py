"""Integration evidence comes from synthetic action rows, never assistant wording."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from task_router.router import Request

pytestmark = pytest.mark.openpoke_integration


async def test_reuse_reaches_upstream_execution_loop_and_persists_draft(service):
    trace = await service.handle(Request("Draft a follow-up", thread_id="thread-0001"))
    assert trace["execution"]["agent_name"] == "Email to Alice"
    assert trace["execution"]["status"] == "awaiting_approval"
    draft = service.store.rows("SELECT * FROM drafts")[0]
    assert (draft["task_id"], draft["thread_id"], draft["recipient"]) == (
        "task-0001",
        "thread-0001",
        "alice.chen@example.test",
    )
    assert draft["status"] == "draft" and not draft["approved_by"]


async def test_failure_cannot_be_reported_as_success_by_model_prose(service):
    trace = await service.handle(Request("Draft a reply", thread_id="thread-0001"), fail=True)
    assert trace["execution"]["status"] == "failed"
    assert service.store.task("task-0001")["state"] == "failed"
    assert service.store.rows("SELECT * FROM drafts") == []


async def test_approval_is_bound_to_actual_task_and_draft(service):
    from integration.openpoke_host import SyntheticTools

    first = await service.handle(Request("Draft email", thread_id="thread-0001"))
    draft_id = first["execution"]["drafts"][0]["id"]
    wrong = SyntheticTools(
        service.store,
        service.store.task("task-0002"),
        Request("Approve and send", approval_draft_id=draft_id),
    )
    with pytest.raises(PermissionError):
        wrong.send_approved_draft()
    sent = await service.handle(
        Request(
            "Approve and send", task_id="task-0001", approval_draft_id=draft_id, conversation_id="approval"
        )
    )
    assert sent["execution"]["status"] == "completed"
    assert service.store.rows("SELECT status,approved_by FROM drafts WHERE id=?", (draft_id,))[0] == {
        "status": "sent",
        "approved_by": sent["request_id"],
    }


async def test_unapproved_send_is_rejected(service):
    trace = await service.handle(Request("Send it", task_id="task-0001"))
    assert trace["execution"]["status"] == "failed"


async def test_same_task_concurrent_execution_has_one_lease(service, monkeypatch):
    from integration.openpoke_host import FixtureChat

    original = FixtureChat.__call__

    async def slower(self, **kwargs):
        await asyncio.sleep(0.04)
        return await original(self, **kwargs)

    monkeypatch.setattr(FixtureChat, "__call__", slower)
    traces = await asyncio.gather(
        *[
            service.handle(Request("Draft email", thread_id="thread-0001", conversation_id=str(i)))
            for i in range(2)
        ]
    )
    assert sorted(t["execution"]["status"] for t in traces) == ["awaiting_approval", "blocked"]
    assert len(service.store.rows("SELECT * FROM drafts")) == 1


async def test_execution_idempotence(service):
    req = Request("Draft email", thread_id="thread-0001")
    first = await service.handle(req)
    second = await service.handle(req)
    assert first == second
    assert len(service.store.rows("SELECT * FROM drafts")) == 1


async def test_clarification_never_dispatches_until_answered(service):
    first = await service.handle(Request("Draft Hawaii trip note to Alice", conversation_id="clarification"))
    assert first["decision"] == "clarify" and service.store.rows("SELECT * FROM executions") == []
    second = await service.handle(Request("task-0003", conversation_id="clarification"))
    draft = second["execution"]["drafts"][0]
    assert draft["recipient"] == "alice.morgan@example.test" and draft["thread_id"] == "thread-0003"


@pytest.mark.parent_app_integration
def test_api_request_correlation_and_no_invented_agent_dispatch(service, monkeypatch, parent_application):
    from server.routing import service as service_module

    monkeypatch.setattr(service_module, "get_routing_service", lambda: service)
    from server.app import app
    import server.routes.routing as routing_routes

    monkeypatch.setattr(routing_routes, "get_routing_service", lambda: service)
    from server.agents.interaction_agent.tools import send_message_to_agent

    assert not send_message_to_agent("Invented owner", "Send mail").success
    with TestClient(app) as client:
        payload = {
            "messages": [{"role": "user", "content": "Draft thread-0001"}],
            "conversation_id": "api-test",
            "request_id": "request-api-test",
        }
        response = client.post("/api/v1/chat/send", json=payload)
        assert response.status_code == 200
        trace = response.json()
        assert trace["request_id"] == "request-api-test" and trace["task_id"] == "task-0001"
        assert client.get("/api/v1/routing/runs/request-api-test").json() == trace
        messages = client.get("/api/v1/chat/history?conversation_id=api-test").json()["messages"]
        assert {m["request_id"] for m in messages} == {"request-api-test"}
        assert client.delete("/api/v1/chat/history").status_code == 409
        assert client.post("/api/v1/gmail/connect", json={}).status_code == 403
        assert client.post("/api/v1/routing/reset", json={"confirm": "wrong"}).status_code == 403
        assert client.get("/api/v1/routing/vectors").json()["dimension"] == 256
        assert client.get("/api/v1/routing/vectors?request_id=unknown-request").status_code == 404
        direct_projection = client.get("/api/v1/routing/vectors?request_id=request-api-test")
        assert direct_projection.status_code == 200 and direct_projection.json()["query"] is None


def test_commitment_is_owner_scoped_and_independent_of_task_state(service):
    from integration.openpoke_host import SyntheticTools

    tools = SyntheticTools(service.store, service.store.task("task-0005"), Request("remind me"))
    result = tools.create_commitment("2027-02-01T09:00:00Z", "Follow up on reunion")
    record = service.store.rows("SELECT * FROM commitments WHERE id=?", (result["commitment_id"],))[0]
    assert record["owner_id"] == "agent-0005" and record["task_id"] == "task-0005"
    assert service.store.task("task-0005")["state"] == "dormant"


async def test_historical_trace_does_not_offer_sent_draft_for_approval(service):
    first = await service.handle(Request("Draft email", task_id="task-0001"))
    draft_id = first["execution"]["drafts"][0]["id"]
    await service.handle(
        Request(
            "Approve and send",
            task_id="task-0001",
            approval_draft_id=draft_id,
            conversation_id="new-approval",
        )
    )
    view = service.trace_view(first)
    assert view["execution"]["drafts"][0]["status"] == "draft"  # historical snapshot stays intact
    assert view["current_drafts"][0]["status"] == "sent"  # UI action uses current truth


async def test_activity_reports_real_direct_lookup_and_tool_lifecycle(service):
    """A known thread reports SQLite + the actual draft tool, never invented vector work."""
    observed = []
    trace = await service.handle(
        Request("Draft a follow-up", thread_id="thread-0001"), on_activity=observed.append
    )
    view = service.trace_view(trace)
    assert observed == view["activity"]
    assert {event["kind"] for event in observed} >= {"lookup", "ownership", "tool"}
    assert not {"embedding", "vector"} & {event["kind"] for event in observed}
    tools = [event for event in observed if event["kind"] == "tool"]
    assert [event["status"] for event in tools] == ["started", "completed"]
    assert tools[0]["operation_id"] == tools[1]["operation_id"]
    assert tools[1]["detail"]["result"]["recipient"] == "alice.chen@example.test"


async def test_vector_activity_is_persisted_and_scoped_to_request(service):
    """The observed search corresponds to actual provider/Chroma calls, and survives reopening."""
    from task_router.service import RoutingService

    first = await service.handle(
        Request("Draft an email to Alice about the Hawaii trip", conversation_id="activity-vector")
    )
    events = service.trace_view(first)["activity"]
    assert {event["kind"] for event in events} >= {"embedding", "vector", "verify", "clarify"}
    assert not any(event["kind"] == "tool" for event in events)  # ambiguity cannot execute
    restarted = RoutingService(service.settings)
    assert restarted.trace_view(first)["activity"] == events
    next_trace = await service.handle(
        Request("Draft a follow-up", thread_id="thread-0001", conversation_id="other")
    )
    assert all(
        event["request_id"] == next_trace["request_id"]
        for event in service.trace_view(next_trace)["activity"]
    )


def test_stream_delivers_request_correlated_activity_then_result(service, monkeypatch, chat_app):
    """The SSE API uses the real runtime, not a timed UI animation or canned transcript."""
    import json
    from task_router import service as service_module

    monkeypatch.setattr(service_module, "get_routing_service", lambda: service)
    app = chat_app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "messages": [{"role": "user", "content": "Draft follow-up in thread-0001"}],
                "request_id": "request-stream-test",
                "conversation_id": "stream-test",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = []
    for frame in response.text.split("\n\n"):
        lines = frame.splitlines()
        if not lines or not lines[0].startswith("event: "):
            continue
        frames.append((lines[0][7:], json.loads(lines[1][6:])))
    assert frames[0][0] == "ready" and frames[-1][0] == "result"
    assert all(data["request_id"] == "request-stream-test" for _, data in frames)
    assert any(
        kind == "activity" and data["kind"] == "tool" and data["status"] == "completed"
        for kind, data in frames
    )
    assert frames[-1][1]["execution"]["status"] == "awaiting_approval"
    assert frames[-1][1]["activity"]


def test_older_conversation_turns_keep_their_trace_and_pending_draft(service, monkeypatch, chat_app):
    """Messages and traces must share history coverage; no invisible 30-turn action limit."""
    from task_router import service as service_module
    import task_router.api as routing_routes
    app = chat_app

    monkeypatch.setattr(service_module, "get_routing_service", lambda: service)
    monkeypatch.setattr(routing_routes, "get_routing_service", lambda: service)
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/chat/send",
            json={
                "messages": [{"role": "user", "content": "Draft thread-0001"}],
                "conversation_id": "long-chat",
            },
        ).json()
        for i in range(31):
            service.router.route(
                Request("Read the known task", task_id="task-0001", conversation_id="long-chat")
            )
        traces = client.get("/api/v1/routing/runs?conversation_id=long-chat").json()
    original = next(trace for trace in traces if trace["request_id"] == first["request_id"])
    assert len(traces) == 32
    assert original["current_drafts"][0]["status"] == "draft"
    assert original["activity"]
