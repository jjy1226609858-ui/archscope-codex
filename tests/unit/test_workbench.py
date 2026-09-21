from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

from archscope.service.workbench import WorkbenchManager
from archscope import __version__


def test_workbench_command_uses_frozen_executable_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    command = WorkbenchManager._serve_command(Path("C:" + "/data/projects.json"), "mini_planner", 61164)
    assert command[:2] == [sys.executable, "serve"]
    assert command[-4:] == ["--project-id", "mini_planner", "--port", "61164"]


def test_workbench_command_uses_module_in_source_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    command = WorkbenchManager._serve_command(Path("C:" + "/data/projects.json"), "mini_planner", 61164)
    assert command[:3] == [sys.executable, "-m", "archscope.service.server"]


def test_workbench_reuse_requires_same_loaded_registry_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({
                "project_id": "mini_planner", "status": "ok",
                "data": {"tool_version": __version__, "registry": {"loaded_digest": "correct"}},
            }).encode("utf-8")

    monkeypatch.setattr("archscope.service.workbench.urllib.request.urlopen", lambda *args, **kwargs: Response())
    assert WorkbenchManager._is_healthy("http://127.0.0.1:12345", "mini_planner", "correct")
    assert not WorkbenchManager._is_healthy("http://127.0.0.1:12345", "mini_planner", "wrong")
    assert not WorkbenchManager._is_healthy("http://127.0.0.1:12345", "other", "correct")
    for unsafe in (
        "https://127.0.0.1:12345", "http://localhost:12345",
        "http://127.0.0.2:12345", "http://example.com:12345",
        "http://127.0.0.1:12345@evil.test", "http://127.0.0.1:12345/elsewhere",
        "http://127.0.0.1:12345?next=http://evil.test",
    ):
        assert not WorkbenchManager._is_healthy(unsafe, "mini_planner", "correct")
