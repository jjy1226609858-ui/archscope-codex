from __future__ import annotations

from pathlib import Path

from archscope.service import ArchScopeApplication


ROOT = Path(__file__).resolve().parents[2]


def app() -> ArchScopeApplication:
    return ArchScopeApplication(ROOT / "examples" / "projects.json")


def test_health_reports_only_implemented_capabilities() -> None:
    result = app().health("mini_planner")
    assert result["status"] == "ok"
    assert result["data"]["capabilities"]["archscope_get_project"] == "available"
    assert result["data"]["capabilities"]["task_repair"] == "available"
    assert result["data"]["capabilities"]["archscope_prepare_task"] == "available"


def test_project_summary_marks_missing_source_not_ready() -> None:
    result = app().get_project("mini_planner")
    assert result["status"] == "ok"
    statuses = {item["id"]: item["implementation_status"] for item in result["data"]["modules"]}
    assert statuses["planning"] == "structural"
    assert statuses["search"] == "implemented"
    assert result["data"]["summary"]["approval_status"] == "unapproved"


def test_unregistered_project_is_a_domain_error() -> None:
    result = app().get_project("missing")
    assert result["status"] == "error"
    assert result["diagnostics"][0]["diagnostic_id"] == "PROJECT_NOT_REGISTERED"


def test_module_detail_contains_children_and_bindings() -> None:
    result = app().get_module("mini_planner", "planning")
    assert result["status"] == "ok"
    assert set(result["data"]["children"]) == {"search", "collision"}
    assert "binding" not in result["data"]["module"]
