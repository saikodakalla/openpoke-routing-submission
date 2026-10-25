"""These tests require only submission/, not the upstream repository."""
from dataclasses import replace
from task_router.dataset import seed_showcase
from task_router.service import RoutingService
from task_router.settings import RoutingSettings
from task_router.router import Request
from task_router.inspection import RegistryInspector


def service(tmp_path):
    s = RoutingService(replace(RoutingSettings(), data_dir=tmp_path, execution_url='http://127.0.0.1:8004'))
    seed_showcase(s.store)
    return s


def test_sql_identity_and_schema_are_independent_of_openpoke(tmp_path):
    s = service(tmp_path)
    trace = s.router.route(Request('Write Alice Chen about the June Hawaii trip'))
    assert trace['task_id'] == 'task-0004' and trace['owner_id'] == 'agent-0004'
    assert trace['verification']['accepted']
    assert not (tmp_path / 'chroma').exists()
    assert RegistryInspector(s.store).rows('tasks')['total'] == 100


def test_usual_place_counts_are_sql_data(tmp_path):
    s = service(tmp_path)
    trace = s.router.route(Request('order pizza from my usual spot'))
    assert trace['decision'] == 'clarify'
    assert [r['frequency'] for r in trace['purchase_evidence']] == [2,2]
    assert not (tmp_path / 'chroma').exists()


async def test_missing_host_never_claims_execution_success(tmp_path):
    s = service(tmp_path)
    result = await s.handle(Request('Draft a reply in thread-0001'))
    assert result['execution']['status'] == 'blocked'
    assert not s.store.rows('SELECT * FROM drafts')
