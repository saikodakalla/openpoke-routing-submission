"""Mock HTTP contracts cover live plumbing without spending API credits."""

from dataclasses import replace
import json

import httpx
import pytest

from task_router.providers import OpenRouter, ProviderError


def test_no_live_calls_without_explicit_enable(service, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    provider = OpenRouter(service.store, replace(service.settings, mode="live"))
    with pytest.raises(ProviderError, match="disabled"):
        provider.embed(["test"])
    assert service.store.rows("SELECT * FROM provider_calls") == []


def test_live_embedding_contract_explicit_model_and_dimension(service, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    settings = replace(service.settings, allow_live=True, dimension=3, embedding_model="test/live-model")

    def handler(req):
        payload = json.loads(req.content)
        assert req.url.path == "/api/v1/embeddings"
        assert payload["model"] == "test/live-model" and payload["dimensions"] == 3
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0, 0.5, 0.2]}], "usage": {"total_tokens": 3}}
        )

    provider = OpenRouter(service.store, settings, transport=httpx.MockTransport(handler))
    assert provider.embed(["test"], "request-live-mock") == [[1.0, 0.5, 0.2]]
    row = service.store.rows("SELECT * FROM provider_calls")[0]
    assert row["status"] == "completed" and row["request_id"] == "request-live-mock"


def test_retry_budget_is_durable_and_bounded(service, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    settings = replace(service.settings, allow_live=True, max_calls=2)
    provider = OpenRouter(
        service.store, settings, transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    with pytest.raises(ProviderError, match="budget"):
        provider.embed(["test"])
    assert len(service.store.rows("SELECT * FROM provider_calls")) == 2
    restarted = OpenRouter(service.store, settings, transport=provider.transport)
    with pytest.raises(ProviderError, match="budget"):
        restarted.embed(["test"])


def test_invalid_dimensions_do_not_silently_change_model(service, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    provider = OpenRouter(
        service.store,
        replace(service.settings, allow_live=True),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})
        ),
    )
    with pytest.raises(ProviderError, match="dimensional"):
        provider.embed(["test"])


def test_auth_error_is_not_retried(service, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    provider = OpenRouter(
        service.store,
        replace(service.settings, allow_live=True),
        transport=httpx.MockTransport(lambda r: httpx.Response(401)),
    )
    with pytest.raises(ProviderError):
        provider.embed(["test"])
    assert len(service.store.rows("SELECT * FROM provider_calls")) == 1


def test_token_and_cost_reservations_reject_before_http(service, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")

    def forbidden(_):
        raise AssertionError("Budget failure must precede network I/O")

    for settings in [
        replace(service.settings, allow_live=True, max_tokens=1),
        replace(service.settings, allow_live=True, max_cost=0),
    ]:
        provider = OpenRouter(service.store, settings, transport=httpx.MockTransport(forbidden))
        with pytest.raises(ProviderError, match="budget"):
            provider.embed(["A nonempty embedding request"])
    assert service.store.rows("SELECT * FROM provider_calls") == []


@pytest.mark.openpoke_integration
async def test_live_mode_uses_real_http_protocol_and_same_synthetic_execution(tmp_path, monkeypatch):
    """Contract test for key-ready live mode: mock HTTP, real runtime/SQLite/Chroma/tools."""
    from task_router.dataset import seed
    from task_router.router import Request
    from task_router.service import RoutingService
    from task_router.settings import RoutingSettings

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    settings = replace(
        RoutingSettings(),
        mode="live",
        allow_live=True,
        data_dir=tmp_path,
        embedding_model="test/real-interface",
        dimension=3,
    )
    s = RoutingService(settings)
    seed(s.store, 20)

    def handler(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0, float(i + 1), 0.3]}
                        for i in range(len(payload["input"]))
                    ],
                    "usage": {"total_tokens": 40},
                },
            )
        assert payload["model"] == settings.chat_model
        assert payload["max_tokens"] == settings.max_output
        if payload["messages"][-1]["role"] == "tool":
            message = {"content": "Done"}
        else:
            message = {
                "content": "",
                "tool_calls": [
                    {
                        "id": "live-contract",
                        "type": "function",
                        "function": {
                            "name": "create_draft",
                            "arguments": '{"body":"Mocked live-model draft"}',
                        },
                    }
                ],
            }
        return httpx.Response(
            200, json={"choices": [{"message": message}], "usage": {"total_tokens": 100, "cost": 0.001}}
        )

    s.provider.transport = httpx.MockTransport(handler)
    assert s.index.repair() == 20
    trace = await s.handle(Request("Draft the follow-up", thread_id="thread-0001"))
    assert trace["mode"] == "live" and trace["execution"]["status"] == "awaiting_approval"
    assert trace["execution"]["drafts"][0]["body"] == "Mocked live-model draft"
    assert len(trace["usage"]) == 2 and all(u["status"] == "completed" for u in trace["usage"])
    assert s.index.name != service_fixture_collection_name()


def service_fixture_collection_name():
    import hashlib

    return "tasks-" + hashlib.sha256(b"fixture-hash-v1:256:summary-v1").hexdigest()[:20]


@pytest.mark.openpoke_integration
async def test_live_natural_request_routes_indexes_and_executes_without_internal_ids(tmp_path, monkeypatch):
    """Key-ready contract: mocked OpenRouter HTTP, actual routing/Chroma/SQLite/draft execution.

    Exercises intake, query embedding, retrieval, new ownership, tool calls and memory
    indexing in one request. Real semantic quality still requires a funded live run.
    """
    from task_router.dataset import seed
    from task_router.router import Request
    from task_router.service import RoutingService
    from task_router.settings import RoutingSettings

    monkeypatch.setenv("OPENROUTER_API_KEY", "mock-key-not-real")
    service = RoutingService(
        replace(
            RoutingSettings(),
            mode="live",
            allow_live=True,
            data_dir=tmp_path,
            embedding_model="test/live-embeddings",
            dimension=3,
        )
    )
    seed(service.store, 20)

    def handler(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [{"index": i, "embedding": [1.0, 0.2, 0.3]} for i in range(len(payload["input"]))]
                },
            )
        if payload.get("response_format"):
            message = {
                "content": json.dumps(
                    {
                        "contact_name": "Kenji",
                        "contact_email": "kenji@example.test",
                        "purpose": "social",
                        "action": "email",
                        "intent": "new",
                        "topic": "birthday greeting",
                    }
                )
            }
        elif payload["messages"][-1]["role"] == "tool":
            message = {"content": "The birthday draft is ready."}
        else:
            message = {
                "content": "",
                "tool_calls": [
                    {
                        "id": "live-draft",
                        "type": "function",
                        "function": {
                            "name": "create_draft",
                            "arguments": json.dumps({"body": "Happy birthday, Kenji!"}),
                        },
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": {"total_tokens": 50}})

    service.provider.transport = httpx.MockTransport(handler)
    service.index.repair()
    trace = await service.handle(Request("Write Kenji a birthday email"))
    assert trace["decision"] == "create" and trace["mode"] == "live"
    assert trace["execution"]["status"] == "awaiting_approval"
    assert trace["execution"]["drafts"][0]["body"] == "Happy birthday, Kenji!"
    assert trace["execution"]["drafts"][0]["recipient"] == "kenji@example.test"
    assert service.index.collection.get(ids=[trace["task_id"]])["ids"] == [trace["task_id"]]
    assert (
        service.index.projection(request_id=trace["request_id"])["query"]["request_id"] == trace["request_id"]
    )
    assert {call["kind"] for call in trace["usage"]} == {"chat", "embedding"}
    assert all(call["status"] == "completed" for call in trace["usage"])
