"""Recovery invariants: the index is disposable; task records are authoritative."""

import json
import subprocess
import sys

import pytest

from task_router.index import TaskIndex
from task_router.providers import CachedEmbeddings, FixtureEmbeddings, ProviderError
from task_router.service import RoutingService
from task_router.store import Store


def test_foreign_keys_and_fts(service):
    """A phantom owner is rejected and text search uses the transactionally updated FTS table."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError), service.store.connect(write=True) as db:
        db.execute(
            "INSERT INTO tasks(id,owner_id,title,summary,state) VALUES('x','missing','a','b','active')"
        )
    service.store.update_summary("task-0001", "uniquely searchable hibiscus")
    assert service.store.keyword("hibiscus")[0]["task_id"] == "task-0001"


def test_actual_chroma_survives_a_new_process(service):
    """A subprocess opens the persisted Chroma collection, not a retained Python list."""
    code = """import sys,json
from pathlib import Path
from task_router.store import Store
from task_router.providers import CachedEmbeddings,FixtureEmbeddings
from task_router.index import TaskIndex
p=Path(sys.argv[1]);s=Store(p/'registry.sqlite3');i=TaskIndex(s,CachedEmbeddings(s,FixtureEmbeddings()),p/'chroma')
print(json.dumps({'count':i.collection.count(),'ids':[r['task_id'] for r in i.query('Kyoto autumn reunion',3)]}))"""
    output = subprocess.check_output(
        [sys.executable, "-c", code, str(service.settings.data_dir)], text=True
    )
    result = json.loads(output)
    assert result["count"] == 20
    assert "task-0005" in result["ids"]


def test_stale_vectors_are_rejected_then_repaired(service):
    """A SQLite update invalidates an old vector before asynchronous reindexing finishes."""
    service.store.update_summary("task-0001", "New task summary")
    assert "task-0001" not in {r["task_id"] for r in service.index.query("Hawaii vacation", 20)}
    assert service.index.repair() == 1
    assert (
        service.index.collection.get(ids=["task-0001"], include=["metadatas"])["metadatas"][0]["version"] == 2
    )


def test_interrupted_index_upsert_replays(service):
    """Crash after Chroma writes, before SQLite ack: the durable pending version remains."""
    service.store.update_summary("task-0001", "Interrupted hibiscus indexing")

    def crash():
        raise RuntimeError("power loss after vector upsert")

    with pytest.raises(RuntimeError):
        service.index.repair(after_upsert=crash)
    state = service.store.rows("SELECT * FROM index_state WHERE task_id='task-0001'")[0]
    assert state["indexed_version"] == 1 and state["pending_version"] == 2
    restarted = RoutingService(service.settings)
    assert restarted.index.repair() == 1
    assert restarted.index.collection.count() == 20


def test_summary_changes_while_embedding_not_acknowledged(service):
    service.store.update_summary("task-0001", "version two")
    called = False

    def update_again():
        nonlocal called
        if not called:
            service.store.update_summary("task-0001", "version three")
            called = True

    assert service.index.repair(after_upsert=update_again) == 2
    assert service.store.rows(
        "SELECT indexed_version,pending_version FROM index_state WHERE task_id='task-0001'"
    )[0] == {"indexed_version": 3, "pending_version": 3}


def test_delete_and_rebuild(service):
    with service.store.connect(write=True) as db:
        db.execute("UPDATE tasks SET state='deleted',version=version+1 WHERE id='task-0001'")
    assert "task-0001" not in {r["task_id"] for r in service.index.query("Hawaii", 20)}
    service.index.repair()
    assert service.index.collection.count() == 19
    service.index.schedule(rebuild=True)
    assert service.index.repair() == 20
    assert service.index.collection.count() == 19


def test_cache_and_collection_isolation(service):
    provider = FixtureEmbeddings(128)
    other = TaskIndex(
        service.store, CachedEmbeddings(service.store, provider), service.settings.data_dir / "chroma"
    )
    assert other.name != service.index.name and other.collection.count() == 0
    service.embeddings.embed(["cache me"])
    misses = service.embeddings.misses
    service.embeddings.embed(["cache me"])
    assert service.embeddings.misses == misses and service.embeddings.hits > 0


def test_bad_provider_dimension_leaves_pending(service):
    service.store.update_summary("task-0001", "dimension failure")
    service.embeddings.provider.embed = lambda *args, **kwargs: [[0.5, 0.2]]
    with pytest.raises(ProviderError):
        service.index.repair()
    assert service.store.rows("SELECT error FROM index_state WHERE task_id='task-0001'")[0]["error"]


def test_projection_uses_actual_vectors(service):
    projection = service.index.projection()
    assert len(projection["points"]) == 20
    assert projection["dimension"] == 256
    assert 0 < projection["explained_variance"] <= 1
    assert projection == service.index.projection()  # fixed ordering and PCA sign convention


def test_dormant_commitments_survive_restart(service):
    restarted = Store(service.store.path)
    assert restarted.task("task-0005")["state"] == "dormant"
    assert restarted.rows("SELECT * FROM commitments WHERE task_id='task-0005'")[0]["state"] == "pending"


def test_new_task_queues_all_known_collections_in_its_creation_transaction(service):
    task_id, _ = service.store.establish("New research project", "research@example.test", "project")
    pending = service.store.rows("SELECT * FROM index_state WHERE task_id=?", (task_id,))
    assert pending[0]["indexed_version"] == 0 and pending[0]["pending_version"] == 1
    service.index.repair()
    assert service.index.collection.count() == 21


async def test_request_projection_reads_cached_query_and_includes_retrieval(service, monkeypatch):
    """The plotted query is the real request embedding in the task PCA basis, with no extra provider call."""
    import numpy as np
    from task_router.router import Request

    trace = await service.handle(Request("Draft an email to Alice about the Hawaii trip"))
    events = service.trace_view(trace)["activity"]
    retrieved = [event for event in events if event["kind"] == "retrieval"]
    assert retrieved and retrieved[-1]["detail"]["candidates"]

    def forbid_provider(*args, **kwargs):
        raise AssertionError("Inspection must not generate embeddings")

    monkeypatch.setattr(service.embeddings.provider, "embed", forbid_provider)
    projection = service.index.projection(limit=2, request_id=trace["request_id"])
    assert projection["query"]["request_id"] == trace["request_id"]
    assert projection["sampled"] == (len(projection["points"]) < service.index.collection.count())
    plotted = {point["id"] for point in projection["points"]}
    assert all(
        candidate["task_id"] in plotted for event in retrieved for candidate in event["detail"]["candidates"]
    )
    # Reconstruct the same basis independently from Chroma and compare the projected query.
    data = service.index.collection.get(
        ids=[point["id"] for point in projection["points"]], include=["embeddings"]
    )
    matrix = np.array(data["embeddings"])
    _, _, axes = np.linalg.svd(matrix - matrix.mean(axis=0), full_matrices=False)
    for axis in axes:
        if axis[np.argmax(np.abs(axis))] < 0:
            axis *= -1
    detail = next(
        event["detail"] for event in events if event["kind"] == "embedding" and event["status"] == "completed"
    )
    vector = json.loads(
        service.store.rows(
            "SELECT vector FROM embedding_cache WHERE content_hash=?", (detail["content_hash"],)
        )[0]["vector"]
    )
    expected = (np.array(vector) - matrix.mean(axis=0)) @ axes[:2].T
    assert np.allclose([projection["query"]["x"], projection["query"]["y"]], expected)


@pytest.mark.openpoke_integration
async def test_direct_projection_does_not_invent_query_or_call_embedding_provider(service, monkeypatch):
    """Known ownership bypasses embeddings; visual inspection must preserve that fact."""
    from task_router.router import Request

    trace = await service.handle(Request("Draft a follow-up in thread-0001"))
    monkeypatch.setattr(
        service.embeddings.provider, "embed", lambda *args: pytest.fail("No provider call allowed")
    )
    assert service.index.projection(request_id=trace["request_id"])["query"] is None


async def test_historical_projection_survives_retrieved_task_deletion(service):
    """Historical retrieval evidence may refer to a removed vector; current inspection stays readable."""
    from task_router.router import Request

    trace = await service.handle(Request("Draft an email to Alice about the Hawaii trip"))
    event = next(event for event in service.trace_view(trace)["activity"] if event["kind"] == "retrieval")
    removed = event["detail"]["candidates"][0]["task_id"]
    with service.store.connect(write=True) as db:
        db.execute("UPDATE tasks SET state='deleted',version=version+1 WHERE id=?", (removed,))
    service.index.repair()
    projection = service.index.projection(limit=2, request_id=trace["request_id"])
    assert removed not in {point["id"] for point in projection["points"]}
    assert projection["query"]["request_id"] == trace["request_id"]
