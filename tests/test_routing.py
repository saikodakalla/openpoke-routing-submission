"""Ownership tests explain why a plausible semantic match is insufficient."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from task_router.router import Request
from task_router.service import RoutingService


def test_known_thread_bypasses_semantics(service, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Known ownership must not embed or search")

    monkeypatch.setattr(service.index, "query", forbidden)
    trace = service.router.route(Request("Draft a follow-up", thread_id="thread-0001"))
    assert (trace["task_id"], trace["owner_id"], trace["path"]) == ("task-0001", "agent-0001", "direct")


def test_recent_followup_uses_confirmed_conversation(service):
    service.router.route(Request("Read this thread", conversation_id="recent", thread_id="thread-0005"))
    trace = service.router.route(Request("Draft a reply to that", conversation_id="recent"))
    assert trace["task_id"] == "task-0005" and trace["path"] == "direct"


def test_names_and_similarity_do_not_establish_ownership(service):
    trace = service.router.route(Request("Draft an email to Alice about the Hawaii trip"))
    assert trace["decision"] == "clarify" and trace["task_id"] is None
    assert "Alice Chen" in trace["response"]
    assert "Alice Morgan" in trace["response"]


def test_pizza_and_travel_have_different_purposes(service):
    trace = service.router.route(Request("Draft pizza lunch email to alice.chen@example.test"))
    assert trace["task_id"] == "task-0002" and trace["path"] == "keyword"
    assert trace["candidates"][0]["components"]["contact_identity"] == 3


def test_two_trips_same_contact_need_dates(service):
    trace = service.router.route(Request("Hawaii trip with alice.chen@example.test"))
    assert trace["decision"] == "clarify"
    assert "February" in trace["response"] and "June" in trace["response"]


def test_clarification_restart_merges_answer(service):
    original = service.router.route(Request("Draft Hawaii trip email to Alice", conversation_id="pending"))
    restarted = RoutingService(service.settings)
    # The reply is an answer to the original request, not new work.
    trace = restarted.router.route(Request("task-0004", conversation_id="pending"))
    assert trace["parent_id"] == original["request_id"]
    assert trace["task_id"] == "task-0004"
    assert "Draft Hawaii trip email" in trace["resolved_request"]["text"]
    assert not trace["new_agent_created"]


def test_date_answer_restarts_lookup(service):
    service.router.route(
        Request("Draft Hawaii trip note to alice.chen@example.test", conversation_id="dates")
    )
    trace = service.router.route(Request("2027-06-20", conversation_id="dates"))
    assert trace["task_id"] == "task-0004"


def test_dormant_tasks_remain_searchable(service):
    trace = service.router.route(Request("Draft Kyoto trip follow-up to kenji@example.test"))
    assert trace["task_id"] == "task-0005"


def test_explicit_conflicting_references_never_dispatch(service):
    trace = service.router.route(Request("Draft note", task_id="task-0001", thread_id="thread-0002"))
    assert trace["decision"] == "clarify" and trace["task_id"] is None


def test_unknown_thread_is_not_inferred_from_similarity(service):
    trace = service.router.route(Request("Hawaii trip", thread_id="thread-missing"))
    assert trace["decision"] == "clarify" and trace["path"] == "direct"


def test_no_match_is_not_proof_of_new_work(service):
    trace = service.router.route(Request("frobnicate the interstellar telescope"))
    assert trace["decision"] == "clarify"
    assert service.store.rows("SELECT count(*) n FROM tasks")[0]["n"] == 20


def test_explicit_new_work_concurrent_creation_is_atomic(service):
    def route(i):
        return service.router.route(
            Request("Draft observatory project to riley@example.test", new_work=True, conversation_id=str(i))
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        traces = list(pool.map(route, range(4)))
    assert len({t["task_id"] for t in traces}) == 1
    assert sum(t["new_agent_created"] for t in traces) == 1
    assert service.store.rows("SELECT count(*) n FROM tasks")[0]["n"] == 21
    assert service.store.rows("SELECT count(*) n FROM agents")[0]["n"] == 21


def test_provider_failure_is_clarification_not_fixture_replacement(service, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(service.index, "query", fail)
    trace = service.router.route(Request("An unfamiliar request"))
    assert trace["decision"] == "clarify" and "retrieval_error" in trace
    direct = service.router.route(
        Request("Read thread", thread_id="thread-0001", conversation_id="available")
    )
    assert direct["decision"] == "reuse"


def test_broader_search_can_recover_owner_outside_first_ten(service, monkeypatch):
    calls = []

    def query(text, limit, **kwargs):
        calls.append(limit)
        return [] if limit == 10 else [{"task_id": "task-0007", "similarity": 0.8}]

    monkeypatch.setattr(service.store, "keyword", lambda *args: [])
    monkeypatch.setattr(service.store, "metadata_candidates", lambda *args: [])
    monkeypatch.setattr(service.index, "query", query)
    trace = service.router.route(Request("Plan travel with noor@example.test"))
    assert calls == [10, 30] and trace["broader_search"]
    assert trace["task_id"] == "task-0007"


def test_background_updates_do_not_become_user_tasks(service):
    trace = service.router.route(Request("Email sent status update", source="agent"))
    assert trace["decision"] == "ignored" and trace["task_id"] is None


def test_idempotent_request_and_identity_conflict(service):
    req = Request("Read thread", thread_id="thread-0001")
    assert service.router.route(req) == service.router.route(req)
    with pytest.raises(ValueError):
        service.router.route(Request("Another instruction", request_id=req.request_id))


def test_unverified_legacy_thread_blocks_reuse(service):
    trace = service.router.route(Request("Read historical project", thread_id="thread-0012"))
    assert trace["decision"] == "clarify"


def test_contact_metadata_recovers_owner_absent_from_keyword_shortlist(service, monkeypatch):
    """Regression from the first held-out run: a financial owner ranked below generic invoice tasks."""
    monkeypatch.setattr(service.store, "keyword", lambda *args: [{"task_id": "task-0010", "rank": -1.0}])
    trace = service.router.route(Request("Draft invoice payment note to priya@example.test"))
    assert trace["task_id"] == "task-0006" and trace["metadata_ids"] == ["task-0006"]
