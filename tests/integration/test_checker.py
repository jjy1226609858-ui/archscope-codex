from __future__ import annotations

import json
import shutil
from pathlib import Path

from archscope.service import ArchScopeApplication


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


def run_check(app: ArchScopeApplication, strict: bool = True) -> dict:
    project = app.get_project("mini_planner")
    result = app.check("mini_planner", project["architecture_digest"], project["code_digest"], strict)
    assert result["status"] == "ok"
    return result["data"]["report"]


def ids(report: dict) -> set[str]:
    return {item["diagnostic_id"] for item in report["diagnostics"]}


def test_archscope_python_backend_self_check_is_clean() -> None:
    app = ArchScopeApplication(ROOT / "examples" / "projects.json")
    project = app.get_project("archscope_self")
    assert project["status"] == "ok"
    result = app.check("archscope_self", project["architecture_digest"], project["code_digest"], True)
    report = result["data"]["report"]
    assert report["status"] == "PASS"
    assert report["approval"]["status"] == "unapproved"
    assert report["acceptance_status"] == "blocked"


def test_checker_pass_is_not_approval(tmp_path: Path) -> None:
    app, _ = isolated_app(tmp_path)
    report = run_check(app)
    assert report["status"] == "PASS"
    assert report["acceptance_status"] == "blocked"
    assert report["approval"]["status"] == "unapproved"
    assert report["coverage"]["source_file_count"] == 11
    assert set(report["module_states"].values()) == {"PASS"}


def test_ownership_and_binding_failures_are_deterministic(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    (project / "src" / "demo" / "orphan.py").write_text("VALUE = 1\n", encoding="utf-8")
    arch = project / "system.arch"
    text = arch.read_text(encoding="utf-8")
    text = text.replace("    - src/demo/data/**/*.py\n", "    - src/demo/data/**/*.py\n    - src/demo/contracts.py\n", 1)
    arch.write_text(text, encoding="utf-8")
    report = run_check(app)
    assert {"UNOWNED_SOURCE", "FILE_OWNERSHIP_CONFLICT"} <= ids(report)
    assert any("no module owner" in item["message"] for item in report["diagnostics"])
    assert report["status"] == "FAIL"


def test_deny_precedence_and_private_modules(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    reporter = project / "src" / "demo" / "reporter" / "api.py"
    reporter.write_text(reporter.read_text(encoding="utf-8") + "\nfrom demo.collision.api import check as forbidden_check\n", encoding="utf-8")
    search = project / "src" / "demo" / "search" / "api.py"
    search.write_text(search.read_text(encoding="utf-8") + "\nfrom demo.collision import check as private_check\n", encoding="utf-8")
    report = run_check(app)
    by_id = {item["diagnostic_id"]: item for item in report["diagnostics"]}
    assert by_id["DEPENDENCY_DENIED"]["rule_id"] == "R_NO_REPORTER_COLLISION"
    assert by_id["DEPENDENCY_DENIED"]["module_id"] == "reporter"
    assert by_id["PRIVATE_IMPORT"]["module_id"] == "search"


def test_permission_is_not_transitive(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    source = project / "src" / "demo" / "main.py"
    source.write_text(source.read_text(encoding="utf-8") + "\nfrom demo.collision.api import check as direct_collision_access\n", encoding="utf-8")
    report = run_check(app)
    violation = next(item for item in report["diagnostics"] if item["diagnostic_id"] == "DEPENDENCY_DENIED")
    assert violation["module_id"] == "app"
    assert violation["target_module_id"] == "collision"
    assert violation["rule_id"] is None


def test_dynamic_import_is_unverified_and_strict_mode_fails(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\ndef late_import():\n    return __import__('demo.collision.api')\n", encoding="utf-8")
    strict = run_check(app, strict=True)
    assert strict["status"] == "FAIL"
    assert "UNVERIFIED_DYNAMIC_IMPORT" in ids(strict)
    advisory = run_check(app, strict=False)
    assert advisory["status"] == "UNVERIFIED"


def test_checker_never_executes_top_level_source_side_effects(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    marker = project / "checker-must-not-create.txt"
    source = project / "src" / "demo" / "data" / "side_effect.py"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n", encoding="utf-8")
    report = run_check(app)
    assert report["status"] == "PASS"
    assert marker.exists() is False


def test_missing_source_root_cannot_be_zero_violation_pass(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    arch = project / "system.arch"
    arch.write_text(arch.read_text(encoding="utf-8").replace("  - src\n", "  - missing-src\n", 1), encoding="utf-8")
    report = run_check(app)
    assert "SOURCE_ROOT_MISSING" in ids(report)
    assert report["status"] == "FAIL"


def test_missing_public_entry_and_report_staleness(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    arch = project / "system.arch"
    arch.write_text(arch.read_text(encoding="utf-8").replace("demo.search.api:plan", "demo.search.api:missing"), encoding="utf-8")
    report = run_check(app)
    assert "ENTRY_SYMBOL_MISSING" in ids(report)

    arch.write_text(arch.read_text(encoding="utf-8").replace("demo.search.api:missing", "demo.search.api:plan"), encoding="utf-8")
    clean = run_check(app)
    assert clean["status"] == "PASS"
    source = project / "src" / "demo" / "contracts.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# code snapshot changed\n", encoding="utf-8")
    refreshed = app.get_project("mini_planner")
    assert refreshed["data"]["latest_check"]["freshness"] == "STALE"
    assert {module["verification_status"] for module in refreshed["data"]["modules"]} == {"STALE"}


def test_external_human_baseline_can_make_clean_report_eligible(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    digest = app.architecture_digest("mini_planner")
    approval = project / ".archscope" / "approvals" / "current.json"
    approval.parent.mkdir(parents=True)
    approval.write_text(json.dumps({
        "architecture_digest": digest,
        "approved_at": "2026-09-21T00:00:00+00:00",
        "reviewer": "human",
        "proposal_id": "manual-fixture",
    }), encoding="utf-8")
    report = run_check(app)
    assert report["approval"]["status"] == "approved"
    assert report["acceptance_status"] == "eligible"
    arch = project / "system.arch"
    original = arch.read_text(encoding="utf-8")
    assert "not a production path planner." in original
    arch.write_text(original.replace("not a production path planner.", "not a certified path planner."), encoding="utf-8")
    changed = run_check(app)
    assert changed["approval"]["status"] == "changed_since_approval"
    assert changed["acceptance_status"] == "blocked"


def test_proposal_is_pending_idempotent_and_never_self_approves(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    original = (project / "system.arch").read_text(encoding="utf-8")
    assert "The BFS search is an example for boundary events, not a production path planner." in original
    candidate = original.replace(
        "The BFS search is an example for boundary events, not a production path planner.",
        "Continue using BFS to verify static boundaries in this candidate.",
    )
    digest = app.architecture_digest("mini_planner")
    first = app.propose_architecture("mini_planner", candidate, digest, "更新未决事项", "proposal-1")
    second = app.propose_architecture("mini_planner", candidate, digest, "更新未决事项", "proposal-1")
    assert first["status"] == "ok", first["diagnostics"]
    assert first["data"]["proposal"]["state"] == "pending_review"
    assert first["data"]["proposal"]["approval"] is None
    assert second["data"]["proposal"]["proposal_id"] == first["data"]["proposal"]["proposal_id"]
    assert app.get_project("mini_planner")["data"]["approval"]["status"] == "unapproved"
    conflict = app.propose_architecture("mini_planner", candidate + "\n", digest, "更新未决事项", "proposal-1")
    assert conflict["diagnostics"][0]["diagnostic_id"] == "IDEMPOTENCY_CONFLICT"
    assert (project / "system.arch").read_text(encoding="utf-8") != candidate
    proposal = first["data"]["proposal"]
    unconfirmed = app.review_proposal(
        "mini_planner", proposal["proposal_id"], digest, proposal["candidate_architecture_digest"], "approve",
    )
    assert unconfirmed["diagnostics"][0]["diagnostic_id"] == "REVIEW_CONFIRMATION_REQUIRED"
    assert "local review interface" in unconfirmed["diagnostics"][0]["message"]
    stale = app.review_proposal(
        "mini_planner",
        proposal["proposal_id"],
        "0" * 64,
        proposal["candidate_architecture_digest"],
        "我已审阅并批准此架构候选",
    )
    assert stale["diagnostics"][0]["diagnostic_id"] == "REVISION_CONFLICT"
    approved = app.review_proposal(
        "mini_planner",
        proposal["proposal_id"],
        digest,
        proposal["candidate_architecture_digest"],
        "我已审阅并批准此架构候选",
    )
    assert approved["status"] == "ok"
    assert approved["data"]["approval"]["status"] == "approved"
    assert (project / "system.arch").read_text(encoding="utf-8") == candidate
