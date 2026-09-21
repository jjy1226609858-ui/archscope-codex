from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from archscope.service import ArchScopeApplication
from archscope.service.api import create_app


ROOT = Path(__file__).resolve().parents[2]


def isolated_client(tmp_path: Path) -> tuple[TestClient, Path]:
    project = tmp_path / "mini_planner"
    shutil.copytree(ROOT / "examples" / "mini_planner", project, ignore=shutil.ignore_patterns(".archscope", "__pycache__"))
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "project_id": "mini_planner", "root": "mini_planner", "arch": "system.arch",
        "control": ".archscope", "profiles": "run_profiles.json",
    }]}), encoding="utf-8")
    application = ArchScopeApplication(registry)
    client = TestClient(create_app(application, default_project_id="mini_planner", static_path=tmp_path / "absent"), base_url="http://127.0.0.1")
    client.headers["X-ArchScope-Session"] = client.get("/api/session").json()["token"]
    return client, project


def request(editor: dict, *, modules: list[dict], flows: list[dict], key: str) -> dict:
    return {
        "project_id": "mini_planner", "modules": modules, "flows": flows,
        "expected_architecture_digest": editor["architecture_digest"],
        "rationale": "Visual editor integration test", "idempotency_key": key,
    }


def test_visual_edit_creates_reviewable_candidate_without_overwriting_arch(tmp_path: Path) -> None:
    client, project = isolated_client(tmp_path)
    editor = client.get("/api/architecture-editor").json()
    original = (project / "system.arch").read_bytes()
    modules = editor["data"]["modules"]
    modules[0]["name"] += " edited"
    response = client.post("/api/visual-proposals", json=request(
        editor, modules=modules, flows=editor["data"]["flows"], key="visual-edit-1",
    ))
    assert response.status_code == 200
    proposal = response.json()["data"]["proposal"]
    assert proposal["state"] == "pending_review"
    assert modules[0]["id"] in proposal["diff"]["modules"]["changed"]
    assert (project / "system.arch").read_bytes() == original
    assert client.get("/api/graph").json()["architecture_digest"] == editor["architecture_digest"]


def test_visual_edit_rejects_stale_or_invalid_structure(tmp_path: Path) -> None:
    client, project = isolated_client(tmp_path)
    editor = client.get("/api/architecture-editor").json()
    original = (project / "system.arch").read_bytes()
    payload = request(editor, modules=editor["data"]["modules"], flows=editor["data"]["flows"], key="stale")
    payload["expected_architecture_digest"] = "0" * 64
    stale = client.post("/api/visual-proposals", json=payload)
    assert stale.status_code == 409
    assert stale.json()["detail"]["diagnostics"][0]["diagnostic_id"] == "REVISION_CONFLICT"
    invalid = request(editor, modules=editor["data"]["modules"], flows=editor["data"]["flows"], key="invalid")
    invalid["flows"].append({"id": "invalid", "from": {"module": "missing", "port": "out"}, "to": {"module": "missing", "port": "in"}, "transport": "in_process", "description": "Invalid"})
    response = client.post("/api/visual-proposals", json=invalid)
    assert response.status_code == 409
    assert response.json()["detail"]["diagnostics"]
    assert (project / "system.arch").read_bytes() == original
    assert not list((project / ".archscope" / "proposals").glob("*/candidate.arch"))


def test_visual_edit_adds_module_and_port_connection_as_pending_diff(tmp_path: Path) -> None:
    client, project = isolated_client(tmp_path)
    editor = client.get("/api/architecture-editor").json()
    original = (project / "system.arch").read_bytes()
    modules = editor["data"]["modules"]
    flows = editor["data"]["flows"]
    source = next(item for item in modules if item["id"] == "data")
    out_port = next(item for item in source["ports"] if item["direction"] == "out")
    modules.append({
        "id": "visual_demo", "name": "Visual demo", "purpose": "Verify graph editing",
        "kind": "leaf", "ports": [{"id": "input", "direction": "in", "domain": out_port["domain"]}],
        "binding": {"files": ["src/visual_demo/**"], "public_imports": [], "entries": []},
    })
    flows.append({
        "id": "data_to_visual_demo", "from": {"module": "data", "port": out_port["id"]},
        "to": {"module": "visual_demo", "port": "input"}, "transport": "in_process", "description": "New visual flow",
    })
    response = client.post("/api/visual-proposals", json=request(editor, modules=modules, flows=flows, key="visual-add-flow"))
    assert response.status_code == 200, response.json()
    diff = response.json()["data"]["proposal"]["diff"]
    assert diff["modules"]["added"] == ["visual_demo"]
    assert diff["flows"]["added"] == ["data_to_visual_demo"]
    assert (project / "system.arch").read_bytes() == original
