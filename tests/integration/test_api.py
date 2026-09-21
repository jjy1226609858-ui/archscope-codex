from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from archscope.service import ArchScopeApplication
from archscope.service.api import create_app


ROOT = Path(__file__).resolve().parents[2]


def client() -> TestClient:
    application = ArchScopeApplication(ROOT / "examples" / "projects.json")
    return TestClient(create_app(application, default_project_id="mini_planner", static_path=ROOT / "does-not-exist"), base_url="http://127.0.0.1")


def test_graph_api_reads_the_same_architecture_model() -> None:
    response = client().get("/api/graph")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "mini_planner"
    assert {node["id"] for node in payload["data"]["nodes"]} >= {"planning", "search", "collision"}
    assert all(edge["kind"] == "declared_data_flow" for edge in payload["data"]["edges"])


def test_module_api_is_read_only_and_returns_ports() -> None:
    response = client().get("/api/modules/search")
    assert response.status_code == 200
    assert {port["id"] for port in response.json()["data"]["module"]["ports"]} == {"scene", "request", "path", "probe", "verdict"}


def test_task_api_lists_persisted_workflow_state() -> None:
    response = client().get("/api/tasks")
    assert response.status_code == 200
    assert isinstance(response.json()["data"]["tasks"], list)
