"""HTTP execution boundary tests with the actual upstream runtime and SQLite.

No real network or paid model: ASGITransport crosses the exact bridge API.
"""

from dataclasses import replace
import httpx
import pytest
from fastapi.testclient import TestClient
from task_router.router import Request
from task_router.bridge import OpenPokeDispatcher


def setup_host(service, monkeypatch):
    from integration import host_server as host

    monkeypatch.setattr(host, "store", service.store)
    monkeypatch.setattr(host, "settings", replace(service.settings, bridge_token="test-only"))
    monkeypatch.setattr(host, "dispatcher", service.dispatcher)
    return host


@pytest.mark.openpoke_integration
async def test_bridge_dispatches_persisted_owner_and_streams_actual_tool_events(service, monkeypatch):
    host = setup_host(service, monkeypatch)
    request = Request("Draft a reply in thread-0001", conversation_id="bridge")
    service.dispatcher = OpenPokeDispatcher(
        service.store,
        replace(service.settings, execution_url="http://127.0.0.1:8004", bridge_token="test-only"),
        transport=httpx.ASGITransport(app=host.app),
    )
    events = []
    trace = await service.handle(request, on_activity=events.append)
    assert trace["execution"]["agent_name"] == "Email to Alice"
    assert trace["execution"]["status"] == "awaiting_approval"
    assert service.store.rows("SELECT * FROM drafts")[0]["thread_id"] == "thread-0001"
    assert any(e["kind"] == "tool" and e["detail"]["tool"] == "create_draft" for e in events)
    again = await service.handle(request)
    assert again["request_id"] == trace["request_id"]
    assert len(service.store.rows("SELECT * FROM drafts")) == 1


@pytest.mark.openpoke_integration
def test_host_rejects_unknown_or_unverified_requests_and_agent_names(service, monkeypatch):
    host = setup_host(service, monkeypatch)
    pending = service.router.route(Request("Which Hawaii plan for Alice?"))
    with TestClient(host.app) as client:
        assert client.post("/execute", json={"request_id": "x"}).status_code == 401
        headers = {"Authorization": "Bearer test-only"}
        assert client.post("/execute", headers=headers, json={"request_id": "x"}).status_code == 404
        assert (
            client.post("/execute", headers=headers, json={"request_id": pending["request_id"]}).status_code
            == 409
        )
        assert (
            client.post(
                "/execute", headers=headers, json={"request_id": "x", "agent_name": "Invented owner"}
            ).status_code
            == 422
        )


async def test_bridge_refuses_a_nonlocal_execution_target(service):
    import pytest

    with pytest.raises(ValueError, match="localhost"):
        OpenPokeDispatcher(service.store, replace(service.settings, execution_url="https://example.com"))


@pytest.mark.openpoke_integration
async def test_unapproved_submission_capabilities_are_not_exposed_to_model(service, monkeypatch):
    from integration.openpoke_host import FixtureChat
    seen = []
    original = FixtureChat.__call__
    async def capture(self, **kwargs):
        seen.extend(s['function']['name'] for s in kwargs.get('tools', []))
        return await original(self, **kwargs)
    monkeypatch.setattr(FixtureChat, '__call__', capture)
    await service.handle(Request('Draft a reply in thread-0001'))
    assert 'create_draft' in seen
    assert 'send_approved_draft' not in seen and 'submit_approved_order' not in seen
