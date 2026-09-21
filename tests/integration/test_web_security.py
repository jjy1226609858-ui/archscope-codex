from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from archscope.service import ArchScopeApplication
from archscope.service.api import create_app
from archscope.service.install import bootstrap_data


ROOT = Path(__file__).resolve().parents[2]


def test_workbench_write_needs_current_session_and_same_origin(tmp_path: Path, monkeypatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    application = ArchScopeApplication(boot["registry"])
    calls: list[tuple[str, str]] = []

    def cancel(project_id: str, operation_id: str) -> dict:
        calls.append((project_id, operation_id))
        return {"status": "ok", "data": {"operation_id": operation_id}}

    monkeypatch.setattr(application, "cancel_run", cancel)
    client = TestClient(create_app(application, default_project_id="mini_planner"), base_url="http://127.0.0.1")
    session = client.get("/api/session")
    assert session.status_code == 200
    assert session.headers["cache-control"] == "no-store"
    assert session.headers["x-frame-options"] == "DENY"
    token = session.json()["token"]
    path = "/api/operations/example/cancel?project_id=mini_planner"

    missing = client.post(path)
    assert missing.status_code == 403
    assert missing.json()["detail"]["diagnostics"][0]["diagnostic_id"] == "HTTP_SESSION_REQUIRED"
    for headers in (
        {"X-ArchScope-Session": token, "Origin": "https://attacker.example"},
        {"X-ArchScope-Session": token, "Origin": "http://127.0.0.1:9999"},
        {"X-ArchScope-Session": token, "Origin": "null"},
        {"X-ArchScope-Session": token, "Sec-Fetch-Site": "cross-site"},
    ):
        rejected = client.post(path, headers=headers)
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["diagnostics"][0]["diagnostic_id"] == "HTTP_ORIGIN_REJECTED"
    assert calls == []

    permitted = client.post(path, headers={"X-ArchScope-Session": token, "Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"})
    assert permitted.status_code == 200
    assert calls == [("mini_planner", "example")]


def test_workbench_token_changes_with_server_and_host_is_restricted(tmp_path: Path) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    application = ArchScopeApplication(boot["registry"])
    first = TestClient(create_app(application, default_project_id="mini_planner"), base_url="http://127.0.0.1")
    second = TestClient(create_app(application, default_project_id="mini_planner"), base_url="http://127.0.0.1")
    assert first.get("/api/session").json()["token"] != second.get("/api/session").json()["token"]
    assert first.get("/api/session", headers={"Host": "attacker.example"}).status_code == 400
    assert first.get("/api/session", headers={"Host": "testserver"}).status_code == 400
    for headers in (
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ):
        response = first.get("/api/session", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["diagnostics"][0]["diagnostic_id"] == "HTTP_ORIGIN_REJECTED"
        assert "token" not in response.text
    assert first.get("/api/session", headers={"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"}).status_code == 200
