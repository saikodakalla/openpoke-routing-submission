"""Natural language regressions: internal IDs must stay an implementation detail.

These use real persistent SQLite/Chroma and the real execution loop. Offline parsing
coverage demonstrates supported phrases, not general semantic-model intelligence.
"""

from dataclasses import replace
from datetime import date
import json

import httpx
import pytest

from task_router.conversation import calendar_date
from task_router.providers import OpenRouter
from task_router.router import Request
from task_router.service import RoutingService


@pytest.mark.openpoke_integration
async def test_drinks_email_only_asks_which_person_then_registers_and_dispatches(service):
    """The reported bug: a new social email must not be routed to an unrelated old Hawaii task."""
    first = await service.handle(
        Request("Send an email to alice about meeting up on Wednesday for drinks", conversation_id="drinks")
    )
    assert first["response"] == "Do you mean Alice Chen or Alice Morgan?"
    assert not service.store.rows("SELECT * FROM executions")
    assert not any(word in first["response"].lower() for word in ["task id", "thread", "@", "2027"])
    restarted = RoutingService(service.settings)
    second = await restarted.handle(Request("Alice Chen", conversation_id="drinks"))
    assert second["parent_id"] == first["request_id"]
    assert second["decision"] == "create" and second["new_agent_created"]
    assert second["execution"]["status"] == "awaiting_approval"
    assert second["execution"]["drafts"][0]["recipient"] == "alice.chen@example.test"
    assert second["task_id"] not in {"task-0001", "task-0002", "task-0003", "task-0004"}
    # Creation and the searchable memory are real, and survive a service restart.
    task = restarted.store.task(second["task_id"])
    assert task["purpose"] == "social" and date.fromisoformat(task["start_date"]).weekday() == 2
    assert restarted.index.collection.get(ids=[task["id"]])["ids"] == [task["id"]]
    assert "task-" not in second["response"] and "thread-" not in second["response"]


@pytest.mark.openpoke_integration
async def test_full_name_and_month_resolve_existing_owner_without_user_ids(service):
    trace = await service.handle(Request("Write an email to Alice Chen about the June Hawaii trip"))
    assert trace["task_id"] == "task-0004"
    assert trace["execution"]["drafts"][0]["recipient"] == "alice.chen@example.test"
    assert trace["execution"]["drafts"][0]["thread_id"] == "thread-0004"
    assert not trace["new_agent_created"]


@pytest.mark.openpoke_integration
async def test_natural_clarification_chain_resolves_person_then_month_after_restart(service):
    first = await service.handle(
        Request("Write an email to Alice about the Hawaii trip", conversation_id="natural")
    )
    assert "Alice Chen" in first["response"] and "Alice Morgan" in first["response"]
    second = await service.handle(Request("Alice Chen", conversation_id="natural"))
    assert second["decision"] == "clarify"
    assert second["response"] == "Do you mean the February or the June plans?"
    restarted = RoutingService(service.settings)
    third = await restarted.handle(Request("The June one", conversation_id="natural"))
    assert third["task_id"] == "task-0004"
    assert third["execution"]["drafts"][0]["thread_id"] == "thread-0004"
    assert not third["new_agent_created"]


async def test_unknown_recipient_is_a_real_world_question_not_a_registry_question(service):
    trace = await service.handle(Request("Write a birthday email to Zephyr"))
    assert trace["response"] == "Who should I address the email to?"
    assert trace["execution"]["status"] == "not_dispatched"


@pytest.mark.openpoke_integration
async def test_unique_saved_name_is_looked_up_without_asking_for_email(service):
    trace = await service.handle(Request("Write Kenji a birthday email"))
    assert trace["decision"] == "create"
    assert trace["execution"]["drafts"][0]["recipient"] == "kenji@example.test"


def test_weekday_and_tomorrow_are_calendar_dates_not_embedding_axes():
    assert calendar_date("Wednesday for drinks", date(2026, 10, 24)) == "2026-10-28"
    assert calendar_date("tomorrow", date(2026, 10, 24)) == "2026-10-25"
    assert calendar_date("the June one", date(2026, 10, 24)) is None  # use saved plans for the actual day
    assert calendar_date("2030-99-99") is None


@pytest.mark.openpoke_integration
async def test_memory_update_failure_preserves_successful_draft_and_queues_repair(service, monkeypatch):
    monkeypatch.setattr(
        service.index, "repair", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline index"))
    )
    trace = await service.handle(Request("Write Kenji a birthday email"))
    assert trace["execution"]["status"] == "awaiting_approval"
    assert trace["indexing_warning"]
    assert service.store.rows(
        "SELECT * FROM index_state WHERE task_id=? AND indexed_version<>pending_version", (trace["task_id"],)
    )


def live_interpreter(service, monkeypatch, output):
    monkeypatch.setenv("OPENROUTER_API_KEY", "mock-key-not-real")
    settings = replace(service.settings, mode="live", allow_live=True)

    def handler(request):
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["provider"]["require_parameters"]
        assert "task-0001" not in json.dumps(payload["messages"])  # no full agent/task roster
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})

    service.router.conversation.provider = OpenRouter(service.store, settings, httpx.MockTransport(handler))
    service.router.conversation.settings = settings


def test_live_intake_contract_and_budget_are_connected_to_the_actual_router(service, monkeypatch):
    """Mocked provider verifies structured language intake; it does not claim real model accuracy."""
    live_interpreter(
        service,
        monkeypatch,
        {
            "contact_name": "Kenji",
            "contact_email": "kenji@example.test",
            "purpose": "social",
            "action": "email",
            "intent": "new",
            "topic": "a birthday greeting",
        },
    )
    trace = service.router.route(Request("Compose a greeting for Kenji's birthday"))
    assert trace["decision"] == "create"
    assert service.store.task(trace["task_id"])["contacts"][0]["email"] == "kenji@example.test"
    assert len(trace["usage"]) == 1 and trace["usage"][0]["status"] == "completed"


def test_language_model_cannot_invent_an_address_or_guess_between_known_people(service, monkeypatch):
    for email in ["invented@elsewhere.test", "alice.chen@example.test"]:
        live_interpreter(
            service,
            monkeypatch,
            {
                "contact_name": "Alice Chen",
                "contact_email": email,
                "purpose": "social",
                "action": "email",
                "intent": "new",
                "topic": "drinks",
            },
        )
        trace = service.router.route(Request("Email Alice about drinks", conversation_id=email))
        assert trace["decision"] == "clarify" and "Alice Chen or Alice Morgan" in trace["response"]
        assert trace["task_id"] is None


def test_invalid_live_intake_does_not_dispatch_or_request_database_identifiers(service, monkeypatch):
    live_interpreter(service, monkeypatch, {"task_id": "task-0001", "owner": "invented"})
    trace = service.router.route(Request("A new instruction"))
    assert trace["decision"] == "clarify" and trace["retrieval_error"]
    assert "task ID" not in trace["response"] and trace["task_id"] is None


@pytest.mark.openpoke_integration
async def test_same_month_in_different_years_has_distinct_choices_and_natural_answer(service):
    with service.store.connect(write=True) as db:
        db.execute("UPDATE tasks SET start_date='2028-06-20' WHERE id='task-0001'")
    first = await service.handle(Request("Write Alice Chen about the Hawaii trip", conversation_id="years"))
    assert "June 2027" in first["response"] and "June 2028" in first["response"]
    second = await service.handle(Request("The 2028 one", conversation_id="years"))
    assert second["task_id"] == "task-0001"
    assert second["execution"]["drafts"][0]["thread_id"] == "thread-0001"


@pytest.mark.openpoke_integration
async def test_shared_contact_and_broad_category_do_not_reuse_an_unrelated_social_email(service):
    birthday = await service.handle(Request("Write Kenji a birthday email", conversation_id="birthday"))
    drinks = await service.handle(Request("Write Kenji about drinks", conversation_id="different-topic"))
    assert drinks["task_id"] != birthday["task_id"]
    assert not service.store.rows("SELECT * FROM drafts WHERE request_id=?", (drinks["request_id"],))
    assert drinks["decision"] == "clarify" and "something new" in drinks["response"]
    confirmed = await service.handle(Request("Something new", conversation_id="different-topic"))
    assert confirmed["decision"] == "create" and confirmed["task_id"] != birthday["task_id"]
    assert confirmed["execution"]["drafts"][0]["recipient"] == "kenji@example.test"


@pytest.mark.openpoke_integration
async def test_ambiguous_name_never_reuses_another_person_with_similar_calendar_history(service):
    noor = await service.handle(
        Request("Send Noor an email about meeting on Wednesday for drinks", conversation_id="noor")
    )
    assert noor["execution"]["status"] == "awaiting_approval"
    alice = await service.handle(
        Request("Send Alice an email about meeting on Wednesday for drinks", conversation_id="alice")
    )
    assert alice["decision"] == "clarify" and alice["task_id"] is None
    assert alice["response"] == "Do you mean Alice Chen or Alice Morgan?"
