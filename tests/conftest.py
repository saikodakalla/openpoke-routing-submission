"""Isolated offline fixtures; original-runtime tests are explicitly opt-in.

The default suite needs only this repository. Optional integration tests copy an
external OpenPoke server into a temporary directory and use its real execution
loop with fixture model responses and synthetic tools, never a replacement loop.
"""

from dataclasses import replace
import importlib
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from task_router.dataset import seed
from task_router.service import RoutingService
from task_router.settings import RoutingSettings


ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption(
        "--openpoke-root",
        default=None,
        help="External OpenPoke checkout for optional real-runtime tests; source is copied, not modified.",
    )


@pytest.fixture(scope="session")
def openpoke_runtime(request, tmp_path_factory):
    supplied = request.config.getoption("--openpoke-root") or os.environ.get("OPENPOKE_TEST_ROOT")
    if not supplied:
        pytest.skip("requires an external OpenPoke checkout: pass --openpoke-root=/path/to/openpoke")
    source = Path(supplied).expanduser().resolve()
    runtime_path = Path("server/agents/execution_agent/runtime.py")
    if not (source / runtime_path).is_file():
        pytest.fail(f"--openpoke-root does not contain {runtime_path}")

    host = tmp_path_factory.mktemp("openpoke-runtime")
    shutil.copytree(
        source / "server",
        host / "server",
        ignore=shutil.ignore_patterns("data", "__pycache__", "*.pyc", ".env", ".env.*"),
    )
    if "dependencies=None" not in (host / runtime_path).read_text():
        patch = ROOT / "integration/openpoke-runtime.patch"
        check = subprocess.run(
            ["git", "apply", "--check", str(patch)], cwd=host, capture_output=True, text=True
        )
        if check.returncode:
            pytest.fail("External runtime is incompatible with the submitted patch: " + check.stderr.strip())
        subprocess.run(["git", "apply", str(patch)], cwd=host, check=True, capture_output=True)

    sys.path.insert(0, str(host))
    try:
        runtime = importlib.import_module("server.agents.execution_agent.runtime")
        if "dependencies" not in inspect.signature(runtime.ExecutionAgentRuntime).parameters:
            pytest.fail("External ExecutionAgentRuntime lacks the submitted dependency-injection seam")
        yield host
    finally:
        sys.path.remove(str(host))


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path, request):
    monkeypatch.setenv("OPENPOKE_MODE", "offline")
    monkeypatch.setenv("OPENPOKE_ROUTING", "tasks")
    monkeypatch.setenv("OPENPOKE_ALLOW_LIVE", "0")
    # Prevent project/user dotenv files from supplying credentials or persistent data.
    monkeypatch.setenv("OPENPOKE_ENV_FILE", str(tmp_path / "no-test-dotenv"))
    monkeypatch.setenv("OPENPOKE_DATA_DIR", str(tmp_path / "host-bootstrap"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    if request.node.get_closest_marker("openpoke_integration"):
        request.getfixturevalue("openpoke_runtime")


@pytest.fixture
def routing_settings(tmp_path, request):
    # A configured URL keeps pure routing/storage tests from importing upstream.
    # Integration tests deliberately use the real injected upstream runtime.
    execution_url = None if request.node.get_closest_marker("openpoke_integration") else "http://127.0.0.1:8004"
    return replace(RoutingSettings(), data_dir=tmp_path, execution_url=execution_url)


@pytest.fixture
def service(routing_settings):
    service = RoutingService(routing_settings)
    seed(service.store, 20)
    service.index.repair()
    return service


@pytest.fixture
def chat_app(service, monkeypatch):
    from task_router import app as app_module
    from task_router import api as api_module

    monkeypatch.setattr(app_module, "get_routing_service", lambda: service)
    monkeypatch.setattr(api_module, "get_routing_service", lambda: service)
    return app_module.app


@pytest.fixture
def parent_application(openpoke_runtime):
    if not (openpoke_runtime / "server/routes/routing.py").is_file():
        pytest.skip("requires the modified parent assessment app's legacy endpoints and dispatch guard")
    return openpoke_runtime
