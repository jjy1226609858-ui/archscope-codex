from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from archscope.service import ArchScopeApplication
from archscope.service.api import create_app

ACKNOWLEDGEMENT = "我已审阅并批准此任务范围"
ROOT = Path(__file__).resolve().parents[2]


def isolated_app(tmp_path: Path) -> tuple[ArchScopeApplication, Path]:
    project = tmp_path / "project"
    target = project / "examples" / "mini_planner"
    shutil.copytree(ROOT / "examples" / "mini_planner", target, ignore=shutil.ignore_patterns(".archscope", "__pycache__"))
    registry = project / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "project_id": "mini_planner", "root": "examples/mini_planner", "arch": "system.arch",
        "control": ".archscope", "profiles": "run_profiles.json",
    }]}), encoding="utf-8")
    return ArchScopeApplication(registry), target


def approve_architecture(app: ArchScopeApplication, project: Path) -> None:
    digest = app.architecture_digest("mini_planner")
    path = project / ".archscope" / "approvals" / "current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "architecture_digest": digest,
        "approved_at": "2026-09-21T00:00:00+00:00",
        "reviewer": "human",
        "proposal_id": "manual-task-fixture",
    }), encoding="utf-8")


def prepare_task(app: ArchScopeApplication, key: str = "task-1") -> dict:
    project = app.get_project("mini_planner")
    check = app.check("mini_planner", project["architecture_digest"], project["code_digest"])
    evidence_ref = check["evidence_refs"][0]
    result = app.prepare_task(
        "mini_planner",
        "search",
        "修复搜索模块并保持公开端口与架构不变",
        [evidence_ref],
        project["architecture_digest"],
        project["code_digest"],
        key,
    )
    assert result["status"] == "ok"
    return result["data"]["task"]


def test_task_requires_scope_review_and_verifies_independently(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app)
    assert task["state"] == "pending_scope_approval"
    assert task["required_tests"] == [
        "tests/test_normal.py",
        "tests/test_no_path.py",
        "tests/test_observation.py",
        "tests/test_bad_input.py",
    ]
    denied = app.update_task("mini_planner", task["task_id"], "claim", task["version"], "codex-a")
    assert denied["diagnostics"][0]["diagnostic_id"] == "APPROVAL_REQUIRED"
    assert "not approved" in denied["diagnostics"][0]["message"]

    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)
    assert reviewed["data"]["task"]["state"] == "waiting_for_codex"
    claimed = app.update_task(
        "mini_planner", task["task_id"], "claim", reviewed["data"]["task"]["version"], "codex-a",
    )
    claimed_task = claimed["data"]["task"]
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# verified in-scope repair\n", encoding="utf-8")
    completed = app.update_task(
        "mini_planner",
        task["task_id"],
        "declare_complete",
        claimed_task["version"],
        "codex-a",
        declaration="实现已完成，请独立验收",
    )
    verified = completed["data"]["task"]
    assert verified["state"] == "verified"
    assert verified["verification"]["result"] == "PASS"
    assert verified["verification"]["tests"]["status"] == "PASS"
    assert verified["verification"]["check"]["status"] == "PASS"
    assert verified["verification"]["changed_files"] == ["src/demo/search/api.py"]
    evidence = app.read_evidence("mini_planner", f"task:{task['task_id']}")
    assert evidence["data"]["evidence"]["value"]["state"] == "verified"


def test_task_claim_is_atomic_and_actor_bound(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app, "atomic")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]

    def claim(actor: str) -> dict:
        return app.update_task("mini_planner", task["task_id"], "claim", reviewed["version"], actor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["codex-a", "codex-b"]))
    assert sum(result["status"] == "ok" for result in results) == 1
    current = app.get_task("mini_planner", task["task_id"])["data"]["task"]
    assert current["state"] == "in_progress"
    other = "codex-b" if current["lease"]["actor_id"] == "codex-a" else "codex-a"
    denied = app.update_task("mini_planner", task["task_id"], "release", current["version"], other)
    assert denied["diagnostics"][0]["diagnostic_id"] == "TASK_LEASE_REQUIRED"
    released = app.update_task(
        "mini_planner", task["task_id"], "release", current["version"], current["lease"]["actor_id"],
    )
    assert released["data"]["task"]["state"] == "waiting_for_codex"


def test_new_session_recovers_task_and_takes_over_expired_lease(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app, "resume")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]
    claimed = app.update_task("mini_planner", task["task_id"], "claim", reviewed["version"], "old-session")["data"]["task"]
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# in-scope unfinished edit\n", encoding="utf-8")
    saved = project / ".archscope" / "tasks" / task["task_id"] / "task.json"
    payload = json.loads(saved.read_text(encoding="utf-8"))
    payload["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    saved.write_text(json.dumps(payload), encoding="utf-8")

    new_session = ArchScopeApplication(app.registry_path)
    resumed = new_session.resume_task("mini_planner", task["task_id"])
    assert resumed["status"] == "ok", resumed
    context = resumed["data"]["context"]
    assert context["task"]["state"] == "in_progress"
    assert context["claimable"] is True
    assert context["freshness"]["changed_files"] == ["src/demo/search/api.py"]
    assert context["evidence"][0]["available"] is True
    denied = new_session.update_task("mini_planner", task["task_id"], "claim", claimed["version"], "new-session")
    assert denied["diagnostics"][0]["diagnostic_id"] == "TASK_RESUME_REQUIRED"
    taken = new_session.update_task(
        "mini_planner", task["task_id"], "claim", claimed["version"], "new-session",
        expected_snapshot_digest=context["freshness"]["snapshot_digest"],
    )
    assert taken["status"] == "ok", taken
    assert taken["data"]["task"]["lease"]["actor_id"] == "new-session"


def test_resume_token_rejects_later_edit_and_out_of_scope_change(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app, "resume-conflict")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]
    claimed = app.update_task("mini_planner", task["task_id"], "claim", reviewed["version"], "old-session")["data"]["task"]
    saved = project / ".archscope" / "tasks" / task["task_id"] / "task.json"
    payload = json.loads(saved.read_text(encoding="utf-8"))
    payload["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    saved.write_text(json.dumps(payload), encoding="utf-8")
    token = app.resume_task("mini_planner", task["task_id"])["data"]["context"]["freshness"]["snapshot_digest"]
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# later edit\n", encoding="utf-8")
    conflict = app.update_task("mini_planner", task["task_id"], "claim", claimed["version"], "new-session", expected_snapshot_digest=token)
    assert conflict["diagnostics"][0]["diagnostic_id"] == "TASK_SNAPSHOT_CONFLICT"
    reporter = project / "src" / "demo" / "reporter" / "api.py"
    reporter.write_text(reporter.read_text(encoding="utf-8") + "\n# out of scope\n", encoding="utf-8")
    stale = app.resume_task("mini_planner", task["task_id"])["data"]["context"]
    assert stale["task"]["state"] == "needs_realign"
    assert stale["claimable"] is False


def test_resume_detects_change_before_first_claim(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app, "preclaim-drift")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# unclaimed edit\n", encoding="utf-8")
    context = ArchScopeApplication(app.registry_path).resume_task("mini_planner", task["task_id"])["data"]["context"]
    assert context["task"]["state"] == "needs_realign"
    assert context["task"]["version"] == reviewed["version"] + 1
    assert context["freshness"]["realign_reason"]


def test_workbench_resume_endpoint_returns_current_context(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app, "workbench-resume")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]
    client = TestClient(create_app(app, default_project_id="mini_planner"), base_url="http://127.0.0.1")
    client.headers["X-ArchScope-Session"] = client.get("/api/session").json()["token"]
    response = client.post(f"/api/tasks/{task['task_id']}/resume?project_id=mini_planner")
    assert response.status_code == 200
    context = response.json()["data"]["context"]
    assert context["task"]["version"] == reviewed["version"]
    assert context["task"]["state"] == "waiting_for_codex"
    assert context["claimable"] is True
    assert context["freshness"]["changed_files"] == []


def test_scope_drift_and_out_of_scope_changes_are_rejected(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    stale_task = prepare_task(app, "stale")
    search = project / "src" / "demo" / "search" / "api.py"
    search.write_text(search.read_text(encoding="utf-8") + "\n# drift before review\n", encoding="utf-8")
    stale = app.approve_task_scope("mini_planner", stale_task["task_id"], stale_task["version"], ACKNOWLEDGEMENT)
    assert stale["diagnostics"][0]["diagnostic_id"] == "TASK_STALE"
    assert app.get_task("mini_planner", stale_task["task_id"])["data"]["task"]["state"] == "needs_realign"

    task = prepare_task(app, "out-of-scope")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]
    claimed = app.update_task("mini_planner", task["task_id"], "claim", reviewed["version"], "codex-a")["data"]["task"]
    reporter = project / "src" / "demo" / "reporter" / "api.py"
    reporter.write_text(reporter.read_text(encoding="utf-8") + "\n# unauthorized change\n", encoding="utf-8")
    completed = app.update_task(
        "mini_planner", task["task_id"], "declare_complete", claimed["version"], "codex-a", declaration="done",
    )["data"]["task"]
    assert completed["state"] == "verification_failed"
    assert completed["verification"]["result"] == "FAIL"
    assert completed["verification"]["out_of_scope_files"] == ["src/demo/reporter/api.py"]


def test_missing_required_test_cannot_be_declared_complete(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    approve_architecture(app, project)
    task = prepare_task(app, "missing-test")
    reviewed = app.approve_task_scope("mini_planner", task["task_id"], task["version"], ACKNOWLEDGEMENT)["data"]["task"]
    claimed = app.update_task("mini_planner", task["task_id"], "claim", reviewed["version"], "codex-a")["data"]["task"]
    (project / "tests" / "test_no_path.py").unlink()
    completed = app.update_task(
        "mini_planner", task["task_id"], "declare_complete", claimed["version"], "codex-a", declaration="done",
    )["data"]["task"]
    assert completed["state"] == "verification_failed"
    assert completed["verification"]["tests"]["status"] == "NOT_RUN"
    assert completed["verification"]["tests"]["missing"] == ["tests/test_no_path.py"]
