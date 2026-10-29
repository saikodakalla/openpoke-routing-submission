"""100-record acceptance cases. Expectations never enter router inputs.

Use a fresh registry to prove that relational cases do not initialize Chroma.
These hash-vector cases test plumbing; the separate live evaluation tests meaning.
"""

import pytest
from task_router.dataset import seed_showcase
from task_router.service import RoutingService
from task_router.router import Request
from task_router.inspection import RegistryInspector


@pytest.fixture
def showcase(routing_settings):
    service = RoutingService(routing_settings)
    seed_showcase(service.store)
    return service


@pytest.mark.openpoke_integration
async def test_easy_lookup_and_inspection_leave_vectors_uncreated(showcase):
    trace = await showcase.handle(Request("Write Alice Chen about the June Hawaii trip"))
    assert trace["task_id"] == "task-0004"
    assert trace["execution"]["status"] == "awaiting_approval"
    inspector = RegistryInspector(showcase.store)
    schema = inspector.schema()
    assert len(inspector.rows("tasks")["rows"]) == 25
    tasks = next(t for t in schema["tables"] if t["name"] == "tasks")
    assert next(c for c in tasks["columns"] if c["name"] == "id")["pk"] == 1
    assert any(f["from"] == "owner_id" and f["table"] == "agents" for f in tasks["foreign_keys"])
    assert showcase.index.projection()["deferred"]
    assert showcase.index.count_existing() == 0
    assert not (showcase.settings.data_dir / "chroma").exists()
    assert not showcase.store.rows("SELECT * FROM embedding_cache")


@pytest.mark.openpoke_integration
async def test_equal_completed_order_counts_ask_then_resume_real_owner(showcase):
    first = await showcase.handle(Request("Order pizza from my usual spot", conversation_id="pizza"))
    assert first["decision"] == "clarify"
    assert (
        "Domino's (2 completed orders)" in first["response"]
        and "Pizza Pizza (2 completed orders)" in first["response"]
    )
    assert not showcase.store.rows("SELECT * FROM executions")
    assert not (showcase.settings.data_dir / "chroma").exists()
    restarted = RoutingService(showcase.settings)
    second = await restarted.handle(Request("dominoes", conversation_id="pizza"))
    assert second["task_id"] == "task-0013" and second["owner_id"] == "agent-0013"
    assert second["execution"]["status"] == "awaiting_approval"
    order = second["execution"]["orders"][0]
    assert order["merchant"] == "Domino's" and order["items"] == "Medium thin-crust margherita"
    assert not (showcase.settings.data_dir / "chroma").exists()
    approval = await restarted.handle(
        Request(
            "Approve this order",
            conversation_id="pizza",
            task_id=second["task_id"],
            approval_order_id=order["id"],
        )
    )
    assert approval["execution"]["status"] == "completed"
    assert showcase.store.rows("SELECT status FROM order_requests")[0]["status"] == "submitted"


async def test_complex_query_initializes_persistent_vectors_then_reuses_cache(showcase):
    await showcase.handle(Request("Ask about the seaside escape and air tickets", conversation_id="complex"))
    assert showcase.index.count_existing() == 100
    assert (showcase.settings.data_dir / "chroma" / "chroma.sqlite3").exists()
    misses = showcase.embeddings.misses
    restarted = RoutingService(showcase.settings)
    assert restarted.index.count_existing() == 100
    restarted.index.query("Ask about the seaside escape and air tickets")
    assert restarted.embeddings.misses == 0 and misses >= 100


def test_inspector_rejects_sql_identifiers_and_follows_actual_foreign_key(showcase):
    inspector = RegistryInspector(showcase.store)
    with pytest.raises(ValueError):
        inspector.rows("tasks; DROP TABLE tasks")
    with pytest.raises(ValueError):
        inspector.rows("tasks", column="id OR 1=1", value="x")
    assert inspector.rows("tasks", column="id", value="x' OR 1=1 --")["total"] == 0
    owner = inspector.rows("agents", column="id", value="agent-0004")
    assert owner["total"] == 1
    with inspector.connect() as db, pytest.raises(Exception, match="readonly"):
        db.execute("DELETE FROM tasks")
