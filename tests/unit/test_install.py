from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archscope.service import ArchScopeApplication
from archscope.service.install import bootstrap_data, configure_target_python, register_project
from archscope.service.interpreter import TargetPythonError, target_python, verify_target_python
from archscope.service.registry import ProjectRegistry
from archscope.service.api import create_app
from archscope.service.tasks import TaskStore
from archscope.cli import _application, _wait_for_operation
from archscope.paths import default_registry_path, default_schema_path, repository_root, target_sdk_path, web_dist_path


ROOT = Path(__file__).resolve().parents[2]


def test_frozen_executable_resolves_sibling_resources_without_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_root = tmp_path / "plugins" / "archscope"
    runtime = plugin_root / "runtime"
    runtime.mkdir(parents=True)
    resources = plugin_root / "resources"
    (resources / "python" / "archscope" / "telemetry").mkdir(parents=True)
    monkeypatch.delenv("ARCHSCOPE_ROOT", raising=False)
    monkeypatch.delenv("ARCHSCOPE_ARCH_SCHEMA", raising=False)
    monkeypatch.delenv("ARCHSCOPE_WEB_DIST", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(runtime / "archscope.exe"))

    assert repository_root() == resources
    assert default_schema_path() == resources / "schemas" / "arch.schema.json"
    assert web_dist_path() == resources / "web" / "dist"
    assert target_sdk_path() == resources / "python"

    override = tmp_path / "override"
    monkeypatch.setenv("ARCHSCOPE_ROOT", str(override))
    assert repository_root() == override


def test_frozen_default_registry_uses_writable_plugin_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ARCHSCOPE_REGISTRY", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    data_root = tmp_path / "plugin-data"
    monkeypatch.setenv("PLUGIN_DATA", str(data_root))
    assert default_registry_path() == data_root / "projects.json"

    monkeypatch.delenv("PLUGIN_DATA")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    assert default_registry_path() == tmp_path / "local-app-data" / "ArchScope" / "plugin-data" / "projects.json"

    explicit = tmp_path / "other" / "registered.json"
    monkeypatch.setenv("ARCHSCOPE_REGISTRY", str(explicit))
    assert default_registry_path() == explicit


def test_missing_registry_cli_reports_diagnostic_instead_of_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing" / "projects.json"
    with pytest.raises(SystemExit) as result:
        _application(str(missing))
    assert result.value.code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["diagnostic_id"] == "REGISTRY_NOT_READY"
    assert payload["registry"] == str(missing)
    assert "bootstrap" in payload["hint"]


def test_cli_wait_keeps_run_owner_until_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    class App:
        calls = 0

        def get_operation(self, project_id: str, operation_id: str) -> dict:
            assert (project_id, operation_id) == ("mini_planner", "op-1")
            self.calls += 1
            state = "running" if self.calls == 1 else "succeeded"
            return {"status": "ok", "data": {"operation": {"state": state, "exit_code": 0}}}

    monkeypatch.setattr("archscope.cli.time.sleep", lambda _: None)
    app = App()
    result = _wait_for_operation(app, "mini_planner", "op-1", 10)
    assert result["data"]["operation"]["state"] == "succeeded"
    assert app.calls == 2


def test_cli_wait_timeout_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    class App:
        def get_operation(self, project_id: str, operation_id: str) -> dict:
            return {"status": "ok", "data": {"operation": {"state": "running"}}}

    ticks = iter([0.0, 2.0])
    monkeypatch.setattr("archscope.cli.time.monotonic", lambda: next(ticks))
    result = _wait_for_operation(App(), "mini_planner", "op-1", 1)
    assert result["status"] == "error"
    assert result["diagnostics"][0]["diagnostic_id"] == "RUN_WAIT_TIMEOUT"


def test_bootstrap_is_idempotent_and_uses_writable_copy(tmp_path: Path) -> None:
    first = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    second = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    assert first["status"] == "created"
    assert second["status"] == "existing"
    registry = Path(first["registry"])
    app = ArchScopeApplication(registry)
    assert app.get_project("mini_planner")["status"] == "ok"
    assert Path(first["demo"]).is_relative_to(tmp_path)
    assert not (Path(first["demo"]) / ".archscope").exists()


def test_register_project_is_atomic_and_requires_explicit_replace(tmp_path: Path) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    project = tmp_path / "custom"
    project.mkdir()
    (project / "system.arch").write_text((ROOT / "examples" / "mini_planner" / "system.arch").read_text(encoding="utf-8").replace("id: mini_planner", "id: custom", 1), encoding="utf-8")
    (project / "run_profiles.json").write_text('{"profiles": []}', encoding="utf-8")
    created = register_project(boot["registry"], project_id="custom", root=project)
    assert created["status"] == "created"
    with pytest.raises(ValueError, match="already registered"):
        register_project(boot["registry"], project_id="custom", root=project)
    replaced = register_project(boot["registry"], project_id="custom", root=project, replace=True, label="Custom")
    assert replaced["status"] == "replaced"
    payload = json.loads(Path(boot["registry"]).read_text(encoding="utf-8"))
    assert [entry["project_id"] for entry in payload["projects"]] == ["mini_planner", "custom"]


def test_registered_target_python_is_used_when_plugin_is_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    project_root = Path(boot["demo"])
    registered = register_project(
        boot["registry"], project_id="mini_planner", root=project_root,
        python=sys.executable, replace=True,
    )
    assert registered["project"]["python"] == str(Path(sys.executable).resolve())
    project = ProjectRegistry(boot["registry"]).get("mini_planner")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert target_python(project) == Path(sys.executable).resolve()


def test_configure_python_changes_only_interpreter_and_replace_preserves_it(tmp_path: Path) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    registry = Path(boot["registry"])
    before = json.loads(registry.read_text(encoding="utf-8"))["projects"][0]
    result = configure_target_python(registry, project_id="mini_planner", python=sys.executable)
    after = json.loads(registry.read_text(encoding="utf-8"))["projects"][0]
    assert result["status"] == "updated"
    assert after == {**before, "python": str(Path(sys.executable).resolve())}

    register_project(registry, project_id="mini_planner", root=boot["demo"], replace=True)
    replaced = json.loads(registry.read_text(encoding="utf-8"))["projects"][0]
    assert replaced["python"] == after["python"]


def test_configure_python_rejects_invalid_input_without_rewriting_registry(tmp_path: Path) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    registry = Path(boot["registry"])
    original = registry.read_bytes()
    with pytest.raises(ValueError, match="registered exactly once"):
        configure_target_python(registry, project_id="absent", python=sys.executable)
    with pytest.raises(ValueError, match="must be absolute"):
        configure_target_python(registry, project_id="mini_planner", python="python.exe")
    with pytest.raises(ValueError, match="TARGET_PYTHON_NOT_FOUND"):
        configure_target_python(registry, project_id="mini_planner", python=tmp_path / "missing-python.exe")
    assert registry.read_bytes() == original


def test_runtime_setup_reports_missing_without_executing_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ARCHSCOPE_TARGET_PYTHON", raising=False)
    monkeypatch.setattr("archscope.service.application.shutil.which", lambda command: None)
    monkeypatch.setattr("archscope.service.interpreter.subprocess.run", lambda *args, **kwargs: pytest.fail("unexpected execution"))
    app = ArchScopeApplication(boot["registry"])
    response = TestClient(create_app(app, default_project_id="mini_planner"), base_url="http://127.0.0.1").get("/api/runtime-setup")
    assert response.status_code == 200
    setup = response.json()["data"]
    assert setup["state"] == "missing"
    assert setup["source"] == "none"
    assert setup["registry"] == str(Path(boot["registry"]).resolve())
    assert setup["cli_prefix"] == [sys.executable]


def test_runtime_setup_does_not_claim_unchecked_alias_is_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ARCHSCOPE_TARGET_PYTHON", raising=False)
    monkeypatch.setattr("archscope.service.application.shutil.which", lambda command: str(tmp_path / "python.exe"))
    app = ArchScopeApplication(boot["registry"])
    setup = app.runtime_setup("mini_planner")["data"]
    assert setup["state"] == "candidate_unverified"
    assert setup["source"] == "path"
    assert app.runtime_setup("unknown")["status"] == "error"


def test_frozen_plugin_never_uses_its_exe_as_target_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    project = ProjectRegistry(boot["registry"]).get("mini_planner")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ARCHSCOPE_TARGET_PYTHON", raising=False)
    monkeypatch.setattr("archscope.service.interpreter.shutil.which", lambda command: None)
    with pytest.raises(TargetPythonError, match="TARGET_PYTHON_NOT_FOUND"):
        target_python(project)


def test_windows_alias_exit_9009_is_rejected_before_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alias = tmp_path / "python.exe"
    alias.write_bytes(b"alias")
    monkeypatch.setattr(
        "archscope.service.interpreter.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 9009, "", "Python not found"),
    )
    with pytest.raises(TargetPythonError, match="9009"):
        verify_target_python(alias)


def test_frozen_plugin_skips_broken_alias_and_accepts_real_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    project = ProjectRegistry(boot["registry"]).get("mini_planner")
    alias = tmp_path / "python3.exe"
    alias.write_bytes(b"alias")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ARCHSCOPE_TARGET_PYTHON", raising=False)
    monkeypatch.setattr("archscope.service.interpreter.shutil.which", lambda command: str(alias) if command == "python3" else sys.executable)
    actual_run = subprocess.run
    monkeypatch.setattr(
        "archscope.service.interpreter.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 9009, "", "Python not found")
        if Path(command[0]) == alias else actual_run(command, **kwargs),
    )
    assert target_python(project) == Path(sys.executable).resolve()


def test_missing_pytest_is_reported_as_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boot = bootstrap_data(tmp_path / "data", ROOT / "examples" / "mini_planner")
    project = ProjectRegistry(boot["registry"]).get("mini_planner")
    monkeypatch.setattr(
        "archscope.service.tasks.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "No module named pytest"),
    )
    result = TaskStore._run_tests(project, ["tests/test_normal.py"], ["src"])
    assert result["status"] == "NOT_RUN"
    assert result["diagnostic_id"] == "PYTEST_NOT_AVAILABLE"
