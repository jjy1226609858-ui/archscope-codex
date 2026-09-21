from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from archscope.service import ArchScopeApplication
from archscope.service.api import create_app
from archscope.service.interpreter import TargetPythonError
from archscope.service.registry import ProjectRegistryError, control_artifact_path
from archscope.telemetry import RuntimeEventWriter


ROOT = Path(__file__).resolve().parents[2]


def isolated_app(tmp_path: Path) -> ArchScopeApplication:
    project = tmp_path / "project"
    target = project / "examples" / "mini_planner"
    shutil.copytree(ROOT / "examples" / "mini_planner", target, ignore=shutil.ignore_patterns(".archscope", "__pycache__"))
    registry = project / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "project_id": "mini_planner", "root": "examples/mini_planner", "arch": "system.arch",
        "control": ".archscope", "profiles": "run_profiles.json",
    }]}), encoding="utf-8")
    return ArchScopeApplication(registry)


def wait_for(app: ArchScopeApplication, operation_id: str, timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = app.get_operation("mini_planner", operation_id, limit=500)
        operation = result["data"]["operation"]
        if operation["state"] in {"succeeded", "failed", "cancelled"}:
            return operation
        time.sleep(0.05)
    raise AssertionError("operation did not finish")


def start(app: ArchScopeApplication, profile_id: str, key: str) -> dict:
    digest = app.architecture_digest("mini_planner")
    result = app.run_profile("mini_planner", profile_id, digest, key)
    assert result["status"] == "ok"
    return result["data"]["operation"]


def test_bad_python_is_rejected_before_creating_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = isolated_app(tmp_path)
    monkeypatch.setattr(
        "archscope.service.operations.target_python",
        lambda project: (_ for _ in ()).throw(TargetPythonError("Target Python startup check failed (exit code 9009)")),
    )
    result = app.run_profile("mini_planner", "demo-search-error", app.architecture_digest("mini_planner"), "no-python")
    assert result["status"] == "error"
    assert result["diagnostics"][0]["diagnostic_id"] == "TARGET_PYTHON_NOT_FOUND"
    assert "9009" in result["diagnostics"][0]["message"]
    project = app.registry.get("mini_planner")
    assert not control_artifact_path(project, "runs").exists()


def test_normal_run_persists_schema_valid_events_and_graph_overlay(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    started = start(app, "demo-normal", "normal-1")
    operation = wait_for(app, started["operation_id"])
    assert operation["state"] == "succeeded"
    assert operation["result"]["report"]["found"] is True
    schema = json.loads((ROOT / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for event in operation["events"]:
        validator.validate({key: value for key, value in event.items() if key != "ingest_seq"})
    graph = app.graph("mini_planner", run_id=operation["run_id"])
    statuses = {node["id"]: node["run_status"] for node in graph["data"]["nodes"]}
    assert statuses["data"] == "succeeded"
    assert statuses["planning"] == "succeeded"
    assert all(edge["run_status"] == "succeeded" for edge in graph["data"]["edges"])


def test_failure_is_attributed_to_the_real_boundary(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    bad_input = wait_for(app, start(app, "demo-bad-input", "bad-1")["operation_id"])
    assert bad_input["state"] == "failed"
    graph = app.graph("mini_planner", run_id=bad_input["run_id"])
    statuses = {node["id"]: node["run_status"] for node in graph["data"]["nodes"]}
    assert statuses["data"] == "failed"
    assert statuses["search"] == "NOT_RUN"

    search_error = wait_for(app, start(app, "demo-search-error", "search-1")["operation_id"])
    graph = app.graph("mini_planner", run_id=search_error["run_id"])
    statuses = {node["id"]: node["run_status"] for node in graph["data"]["nodes"]}
    assert statuses["search"] == "failed"
    assert statuses["planning"] == "failed"


def test_idempotency_and_cancellation(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    first = start(app, "demo-normal", "same-key")
    second = start(app, "demo-normal", "same-key")
    assert second["operation_id"] == first["operation_id"]
    conflict = app.run_profile("mini_planner", "demo-bad-input", app.architecture_digest("mini_planner"), "same-key")
    assert conflict["diagnostics"][0]["diagnostic_id"] == "IDEMPOTENCY_CONFLICT"
    wait_for(app, first["operation_id"])

    slow = start(app, "demo-slow", "slow-1")
    cancelled = app.cancel_run("mini_planner", slow["operation_id"])
    assert cancelled["status"] == "ok"
    assert wait_for(app, slow["operation_id"])["state"] == "cancelled"


def test_disabling_probe_preserves_business_result_and_marks_observation_gap(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    profiles = json.loads(project.profile_path.read_text(encoding="utf-8"))
    profiles["profiles"].append({
        "id": "demo-normal-unobserved",
        "label": "正常规划（不观测）",
        "module": "demo.main",
        "scenario": "scenarios/normal.json",
        "observe": False,
    })
    project.profile_path.write_text(json.dumps(profiles, ensure_ascii=False), encoding="utf-8")
    observed = wait_for(app, start(app, "demo-normal", "probe-on")["operation_id"])
    unobserved = wait_for(app, start(app, "demo-normal-unobserved", "probe-off")["operation_id"])
    assert observed["state"] == unobserved["state"] == "succeeded"
    assert observed["result"]["report"] == unobserved["result"]["report"]
    assert observed["observation_enabled"] is True
    assert unobserved["observation_enabled"] is False
    assert observed["event_count"] > 0
    assert unobserved["event_count"] == 0
    assert observed["result"]["target_duration_ms"] >= 0
    assert unobserved["result"]["target_duration_ms"] >= 0
    graph = app.graph("mini_planner", run_id=unobserved["run_id"])
    assert all(node["run_status"] == "NOT_RUN" for node in graph["data"]["nodes"])


def test_disabling_probe_preserves_failure_semantics(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    profiles = json.loads(project.profile_path.read_text(encoding="utf-8"))
    for original in profiles["profiles"][:]:
        if original["id"] not in {"demo-bad-input", "demo-search-error"}:
            continue
        profiles["profiles"].append({**original, "id": original["id"] + "-unobserved", "observe": False})
    project.profile_path.write_text(json.dumps(profiles, ensure_ascii=False), encoding="utf-8")
    for profile_id in ("demo-bad-input", "demo-search-error"):
        observed = wait_for(app, start(app, profile_id, profile_id + "-on")["operation_id"])
        unobserved = wait_for(app, start(app, profile_id + "-unobserved", profile_id + "-off")["operation_id"])
        assert observed["state"] == unobserved["state"] == "failed"
        assert observed["result"]["error_type"] == unobserved["result"]["error_type"]
        assert observed["result"]["message"] == unobserved["result"]["message"]
        assert observed["event_count"] > 0
        assert unobserved["event_count"] == 0


def test_web_run_rejects_arbitrary_command_and_unapproved_profile(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    client = TestClient(create_app(app, default_project_id="mini_planner"), base_url="http://127.0.0.1")
    client.headers["X-ArchScope-Session"] = client.get("/api/session").json()["token"]
    request = {
        "project_id": "mini_planner", "profile_id": "demo-normal",
        "expected_architecture_digest": app.architecture_digest("mini_planner"),
        "idempotency_key": "web-rejection",
    }
    for field, value in (("command", "powershell -Command whoami"), ("cwd", str(tmp_path.parent))):
        rejected = client.post("/api/runs", json={**request, field: value})
        assert rejected.status_code == 422
    unknown = client.post("/api/runs", json={**request, "profile_id": "not-approved"})
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["diagnostics"][0]["diagnostic_id"] == "RUN_PROFILE_NOT_FOUND"


def test_evidence_and_profile_paths_cannot_escape_project(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret":"DO_NOT_READ"}', encoding="utf-8")
    rejected = app.read_evidence("mini_planner", "check:../../outside")
    assert rejected["diagnostics"][0]["diagnostic_id"] == "EVIDENCE_REF_INVALID"
    assert "DO_NOT_READ" not in json.dumps(rejected)
    project = app.registry.get("mini_planner")
    profiles = json.loads(project.profile_path.read_text(encoding="utf-8"))
    profiles["profiles"].append({"id": "escape", "module": "demo.main", "scenario": "../../outside.json"})
    project.profile_path.write_text(json.dumps(profiles), encoding="utf-8")
    denied = app.run_profile("mini_planner", "escape", app.architecture_digest("mini_planner"), "escape-key")
    assert denied["diagnostics"][0]["diagnostic_id"] == "RUN_PROFILES_INVALID"

    profiles["profiles"][-1]["scenario"] = "scenarios/linked.json"
    linked = project.root / "scenarios" / "linked.json"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("此 Windows 环境不能创建测试符号链接")
    project.profile_path.write_text(json.dumps(profiles), encoding="utf-8")
    denied_link = app.run_profile("mini_planner", "escape", app.architecture_digest("mini_planner"), "linked-key")
    assert denied_link["diagnostics"][0]["diagnostic_id"] == "RUN_PROFILES_INVALID"


def test_windows_junction_cannot_escape_scenario_or_control_paths(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows directory junction test")
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    outside = tmp_path / "outside-directory"
    outside.mkdir()
    (outside / "secret.json").write_text('{"secret":"DO_NOT_READ"}', encoding="utf-8")

    def junction(link: Path) -> None:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "New-Item -ItemType Junction -Path $env:ARCHSCOPE_JUNCTION_LINK -Target $env:ARCHSCOPE_JUNCTION_TARGET | Out-Null"],
            env={**os.environ, "ARCHSCOPE_JUNCTION_LINK": str(link), "ARCHSCOPE_JUNCTION_TARGET": str(outside)},
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode:
            pytest.skip(f"Windows directory junction unavailable: {result.stderr.strip()}")

    scenario_link = project.root / "scenarios" / "linked-directory"
    junction(scenario_link)
    profiles = json.loads(project.profile_path.read_text(encoding="utf-8"))
    profiles["profiles"].append({"id": "junction-escape", "module": "demo.main", "scenario": "scenarios/linked-directory/secret.json"})
    project.profile_path.write_text(json.dumps(profiles), encoding="utf-8")
    denied = app.run_profile("mini_planner", "junction-escape", app.architecture_digest("mini_planner"), "junction-escape-key")
    assert denied["diagnostics"][0]["diagnostic_id"] == "RUN_PROFILES_INVALID"
    assert "DO_NOT_READ" not in json.dumps(denied)

    project.control_path.mkdir(exist_ok=True)
    junction(project.control_path / "linked-directory")
    with pytest.raises(ProjectRegistryError, match="ARTIFACT_PATH_ESCAPE"):
        control_artifact_path(project, "linked-directory", "secret.json")


def test_restarted_manager_does_not_trust_unconfirmed_result_file(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    operation_id = "a" * 32
    run_dir = project.control_path / "runs" / operation_id
    run_dir.mkdir(parents=True)
    operation_path = run_dir / "operation.json"
    operation_path.write_text(json.dumps({
        "operation_id": operation_id, "run_id": operation_id, "project_id": "mini_planner",
        "architecture_digest": app.architecture_digest("mini_planner"),
        "state": "running", "pid": 12345, "exit_code": None, "result": None,
    }), encoding="utf-8")
    (run_dir / "result.json").write_text('{"status":"succeeded"}', encoding="utf-8")
    restarted = ArchScopeApplication(app.registry_path)
    recovered = restarted.get_operation("mini_planner", operation_id)["data"]["operation"]
    assert recovered["state"] == "observation_lost"
    assert recovered["diagnostic_id"] == "RUN_OWNER_LOST"
    assert recovered["exit_code"] is None
    assert recovered["result"] is None
    assert json.loads(operation_path.read_text(encoding="utf-8"))["state"] == "running"
    denied = restarted.cancel_run("mini_planner", operation_id)
    assert denied["diagnostics"][0]["diagnostic_id"] == "CANCEL_NOT_AVAILABLE"

    app.runs._processes[operation_id] = object()  # simulate a still-owned process handle
    try:
        owned = app.get_operation("mini_planner", operation_id)["data"]["operation"]
        assert owned["state"] == "running"
        assert owned["exit_code"] is None
    finally:
        app.runs._processes.pop(operation_id, None)


def test_restarted_manager_replay_does_not_return_stale_running_state(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    started = start(app, "demo-slow", "restart-replay")
    restarted = ArchScopeApplication(app.registry_path)
    replay = restarted.run_profile(
        "mini_planner", "demo-slow", app.architecture_digest("mini_planner"), "restart-replay"
    )["data"]["operation"]
    assert replay["operation_id"] == started["operation_id"]
    assert replay["state"] == "observation_lost"
    assert replay["diagnostic_id"] == "RUN_OWNER_LOST"
    assert replay["exit_code"] is None
    app.cancel_run("mini_planner", started["operation_id"])
    assert wait_for(app, started["operation_id"])["state"] == "cancelled"


@pytest.mark.parametrize("result_text,diagnostic_id", [
    (None, "RUN_RESULT_MISSING"),
    ("not json", "RUN_RESULT_INVALID"),
    ("[]", "RUN_RESULT_INVALID"),
])
def test_clean_process_exit_without_valid_result_is_not_success(tmp_path: Path, result_text: str | None, diagnostic_id: str) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    operation_id = "b" * 32
    run_dir = project.control_path / "runs" / operation_id
    run_dir.mkdir(parents=True)
    operation_path = run_dir / "operation.json"
    operation_path.write_text(json.dumps({"operation_id": operation_id, "state": "running"}), encoding="utf-8")
    result_path = run_dir / "result.json"
    if result_text is not None:
        result_path.write_text(result_text, encoding="utf-8")
    app.runs._monitor(operation_id, operation_path, result_path, SimpleNamespace(wait=lambda: 0), StringIO(), StringIO())
    recorded = json.loads(operation_path.read_text(encoding="utf-8"))
    assert recorded["state"] == "observation_lost"
    assert recorded["exit_code"] == 0
    assert recorded["result"]["diagnostic_id"] == diagnostic_id


def test_event_cursor_skips_retransmits_and_reports_corruption(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    started = start(app, "demo-normal", "cursor-test")
    completed = wait_for(app, started["operation_id"])
    assert completed["event_count"] == 131
    project = app.registry.get("mini_planner")
    event_path = project.control_path / "runs" / started["operation_id"] / "events.jsonl"
    first_line = event_path.read_text(encoding="utf-8").splitlines()[0]
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(first_line + "\n")
    cursor = 0
    collected: list[str] = []
    while True:
        page = app.get_operation("mini_planner", started["operation_id"], cursor=cursor, limit=25)["data"]["operation"]
        collected.extend(event["event_id"] for event in page["events"])
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
        if not page["has_more_events"]:
            break
    assert len(collected) == len(set(collected)) == 131
    assert page["event_count"] == 131
    assert page["duplicate_event_count"] == 1
    assert page["event_line_count"] == 132
    assert page["state"] == "succeeded"
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
    damaged = app.get_operation("mini_planner", started["operation_id"], cursor=cursor, limit=25)["data"]["operation"]
    assert damaged["events"] == []
    assert damaged["next_cursor"] == 133
    assert damaged["invalid_event_count"] == 1
    assert damaged["state"] == "observation_lost"
    assert damaged["diagnostic_id"] == "RUN_EVENTS_INVALID"


def test_out_of_order_finish_and_duplicate_do_not_regress_module_status(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    operation_id = "c" * 32
    run_dir = project.control_path / "runs" / operation_id
    run_dir.mkdir(parents=True)
    (run_dir / "operation.json").write_text(json.dumps({
        "operation_id": operation_id, "run_id": operation_id, "project_id": "mini_planner",
        "architecture_digest": app.architecture_digest("mini_planner"), "state": "succeeded",
        "result": {"status": "succeeded"}, "exit_code": 0,
    }), encoding="utf-8")
    event_path = run_dir / "events.jsonl"
    probe = RuntimeEventWriter(event_path, project_id="mini_planner", run_id=operation_id,
                               arch_revision=app.architecture_digest("mini_planner"), code_revision="test")
    probe.emit("module.started", module_id="search")
    probe.emit("module.finished", module_id="search")
    probe.close()
    started_line, finished_line = event_path.read_text(encoding="utf-8").splitlines()
    event_path.write_text("\n".join([finished_line, started_line, finished_line]) + "\n", encoding="utf-8")
    operation = app.get_operation("mini_planner", operation_id)["data"]["operation"]
    assert operation["event_count"] == 2
    assert operation["duplicate_event_count"] == 1
    graph = app.graph("mini_planner", run_id=operation_id)
    assert next(node for node in graph["data"]["nodes"] if node["id"] == "search")["run_status"] == "succeeded"

    finish = json.loads(finished_line)
    start_event = json.loads(started_line)
    finish["producer_seq"] = 0
    start_event["producer_seq"] = 1
    event_path.write_text("\n".join(json.dumps(item) for item in (finish, start_event)) + "\n", encoding="utf-8")
    inconsistent = app.graph("mini_planner", run_id=operation_id)
    assert next(node for node in inconsistent["data"]["nodes"] if node["id"] == "search")["run_status"] == "unknown"


def test_graph_replays_events_beyond_first_page(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    operation_id = "d" * 32
    run_dir = project.control_path / "runs" / operation_id
    run_dir.mkdir(parents=True)
    (run_dir / "operation.json").write_text(json.dumps({
        "operation_id": operation_id, "run_id": operation_id, "project_id": "mini_planner",
        "architecture_digest": app.architecture_digest("mini_planner"), "state": "failed",
        "result": {"status": "failed"}, "exit_code": 1,
    }), encoding="utf-8")
    probe = RuntimeEventWriter(run_dir / "events.jsonl", project_id="mini_planner", run_id=operation_id,
                               arch_revision=app.architecture_digest("mini_planner"), code_revision="test")
    for _ in range(500):
        probe.emit("flow.transferred", flow_id="F_PROBE", payload={"summary": {"count": 1}})
    probe.emit("module.started", module_id="search")
    probe.emit("module.failed", module_id="search", payload={"error_type": "RuntimeError", "message": "late failure"})
    probe.close()
    graph = app.graph("mini_planner", run_id=operation_id)
    assert graph["status"] == "ok"
    assert graph["data"]["operation"]["event_count"] == 502
    assert len(graph["data"]["operation"]["events"]) == 502
    assert next(node for node in graph["data"]["nodes"] if node["id"] == "search")["run_status"] == "failed"
    module = app.get_module("mini_planner", "search", run_id=operation_id)
    assert module["data"]["summary"]["run_status"] == "failed"
    too_large = app.runs.get_for_overlay(project, operation_id, max_events=500)
    assert too_large["state"] == "observation_lost"
    assert too_large["diagnostic_id"] == "RUN_EVENT_OVERLAY_LIMIT"
    assert too_large["events"] == []

    loss_probe = RuntimeEventWriter(run_dir / "events.jsonl", project_id="mini_planner", run_id=operation_id,
                                    arch_revision=app.architecture_digest("mini_planner"), code_revision="test")
    loss_probe.emit("events.dropped", payload={"count": 2})
    loss_probe.close()
    lost = app.graph("mini_planner", run_id=operation_id)
    assert lost["data"]["operation"]["state"] == "observation_lost"
    assert lost["data"]["operation"]["loss_marker_count"] == 1
    assert next(node for node in lost["data"]["nodes"] if node["id"] == "search")["run_status"] == "unknown"


def test_run_idempotency_binds_code_profile_and_snapshotted_scenario(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    scenario = project.root / "scenarios" / "normal.json"
    original = scenario.read_bytes()
    first = start(app, "demo-normal", "fixed-input")
    wait_for(app, first["operation_id"])
    snapshot = project.control_path / "runs" / first["operation_id"] / "normal.json"
    assert snapshot.read_bytes() == original
    assert app.run_profile("mini_planner", "demo-normal", app.architecture_digest("mini_planner"), "fixed-input")["data"]["operation"]["operation_id"] == first["operation_id"]

    payload = json.loads(original)
    payload["width"] += 1
    scenario.write_text(json.dumps(payload), encoding="utf-8")
    assert snapshot.read_bytes() == original
    scenario_conflict = app.run_profile("mini_planner", "demo-normal", app.architecture_digest("mini_planner"), "fixed-input")
    assert scenario_conflict["diagnostics"][0]["diagnostic_id"] == "IDEMPOTENCY_CONFLICT"
    scenario.write_bytes(original)

    source = project.root / "src" / "demo" / "search" / "api.py"
    original_source = source.read_text(encoding="utf-8")
    source.write_text(original_source + "\n# revised implementation\n", encoding="utf-8")
    code_conflict = app.run_profile("mini_planner", "demo-normal", app.architecture_digest("mini_planner"), "fixed-input")
    assert code_conflict["diagnostics"][0]["diagnostic_id"] == "IDEMPOTENCY_CONFLICT"
    source.write_text(original_source, encoding="utf-8")

    profile = json.loads(project.profile_path.read_text(encoding="utf-8"))
    profile["profiles"][0]["label"] = "修改后的档案名称"
    project.profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    profile_conflict = app.run_profile("mini_planner", "demo-normal", app.architecture_digest("mini_planner"), "fixed-input")
    assert profile_conflict["diagnostics"][0]["diagnostic_id"] == "IDEMPOTENCY_CONFLICT"


def test_control_artifact_resolver_rejects_parent_escape(tmp_path: Path) -> None:
    app = isolated_app(tmp_path)
    project = app.registry.get("mini_planner")
    safe = control_artifact_path(project, "runs", "a" * 32, "operation.json")
    assert safe.is_relative_to(project.control_path)
    with pytest.raises(ProjectRegistryError, match="ARTIFACT_PATH_ESCAPE"):
        control_artifact_path(project, "runs", "..", "..", "outside.json")
