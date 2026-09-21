from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from archscope.service import ArchScopeApplication


ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "mini_planner"
ACKNOWLEDGEMENT = "我已审阅并批准此架构候选"


def isolated_app(tmp_path: Path) -> tuple[ArchScopeApplication, Path]:
    project = tmp_path / "mini_planner"
    shutil.copytree(ROOT / "examples" / "mini_planner", project, ignore=shutil.ignore_patterns(".archscope", "__pycache__"))
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "project_id": PROJECT_ID, "root": "mini_planner", "arch": "system.arch",
        "control": ".archscope", "profiles": "run_profiles.json",
    }]}), encoding="utf-8")
    return ArchScopeApplication(registry), project


def approve_change(app: ArchScopeApplication, project: Path, before: str, after: str, key: str) -> str:
    original = (project / "system.arch").read_text(encoding="utf-8")
    assert before in original
    base = app.architecture_digest(PROJECT_ID)
    proposal = app.propose_architecture(PROJECT_ID, original.replace(before, after), base, "历史版本验证", key)
    assert proposal["status"] == "ok"
    metadata = proposal["data"]["proposal"]
    approved = app.review_proposal(
        PROJECT_ID, metadata["proposal_id"], base, metadata["candidate_architecture_digest"], ACKNOWLEDGEMENT,
    )
    assert approved["status"] == "ok"
    return approved["architecture_digest"]


def test_historical_architecture_and_approval_survive_two_revisions(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    original = app.get_project(PROJECT_ID)
    first_digest = original["architecture_digest"]
    old_name = original["data"]["project"]["name"]
    second_digest = approve_change(app, project, old_name, "历史验证第一版", "history-1")
    third_digest = approve_change(app, project, "历史验证第一版", "历史验证第二版", "history-2")
    assert len({first_digest, second_digest, third_digest}) == 3

    first = app.get_project(PROJECT_ID, first_digest)
    assert first["status"] == "ok"
    assert first["data"]["historical"] is True
    assert first["data"]["project"]["name"] == old_name
    assert first["code_digest"] is None
    assert first["data"]["modules"][0]["implementation_status"] == "historical_unknown"
    assert first["data"]["approval"]["status"] == "historical_unapproved_or_missing"

    second = app.get_project(PROJECT_ID, second_digest)
    assert second["data"]["project"]["name"] == "历史验证第一版"
    assert second["data"]["approval"]["status"] == "historical_approved"
    assert second["data"]["approval"]["baseline"]["architecture_digest"] == second_digest
    assert app.get_module(PROJECT_ID, "search", second_digest)["data"]["historical"] is True
    graph = app.graph(PROJECT_ID, second_digest)
    assert graph["data"]["historical"] is True
    assert graph["data"]["project"]["name"] == "历史验证第一版"
    assert app.read_evidence(PROJECT_ID, f"arch:{second_digest}")["data"]["evidence"]["value"]["project"]["name"] == "历史验证第一版"
    assert app.read_evidence(PROJECT_ID, f"approval:{second_digest}")["data"]["evidence"]["value"]["status"] == "historical_approved"


def test_old_run_keeps_its_revision_and_rejects_new_graph_overlay(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    digest = app.architecture_digest(PROJECT_ID)
    started = app.run_profile(PROJECT_ID, "demo-normal", digest, "old-run")
    assert started["status"] == "ok"
    run_id = started["data"]["operation"]["run_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        operation = app.get_operation(PROJECT_ID, run_id)
        if operation["data"]["operation"]["state"] == "succeeded":
            break
        time.sleep(0.05)
    assert operation["data"]["operation"]["state"] == "succeeded"
    old_name = app.get_project(PROJECT_ID)["data"]["project"]["name"]
    approve_change(app, project, old_name, "新名称", "after-run")

    historical_run = app.get_operation(PROJECT_ID, run_id)
    assert historical_run["architecture_digest"] == digest
    assert historical_run["data"]["architecture_snapshot_status"] == "available"
    assert app.graph(PROJECT_ID, digest, run_id)["status"] == "ok"
    mismatch = app.graph(PROJECT_ID, run_id=run_id)
    assert mismatch["diagnostics"][0]["diagnostic_id"] == "RUN_REVISION_MISMATCH"
    assert app.read_evidence(PROJECT_ID, f"run:{run_id}")["architecture_digest"] == digest
    (project / "system.arch").write_text("invalid: [", encoding="utf-8")
    assert app.get_operation(PROJECT_ID, run_id)["data"]["architecture_snapshot_status"] == "available"
    assert app.read_evidence(PROJECT_ID, f"arch:{digest}")["status"] == "ok"


def test_archive_corruption_and_unknown_revision_are_explicit(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    old_digest = app.architecture_digest(PROJECT_ID)
    old_name = app.get_project(PROJECT_ID)["data"]["project"]["name"]
    approve_change(app, project, old_name, "新名称", "corrupt")
    missing = app.get_project(PROJECT_ID, "a" * 64)
    assert missing["diagnostics"][0]["diagnostic_id"] == "ARCHIVE_NOT_FOUND"
    invalid = app.get_project(PROJECT_ID, "../bad")
    assert invalid["diagnostics"][0]["diagnostic_id"] == "ARCHIVE_REVISION_INVALID"
    archived = project / ".archscope" / "architectures" / f"{old_digest}.arch"
    archived.write_text(archived.read_text(encoding="utf-8").replace(old_name, "篡改内容"), encoding="utf-8")
    corrupt = app.get_project(PROJECT_ID, old_digest)
    assert corrupt["diagnostics"][0]["diagnostic_id"] == "ARCHIVE_CORRUPT"


def test_legacy_current_approval_is_preserved_and_archive_survives_broken_current(tmp_path: Path) -> None:
    app, project = isolated_app(tmp_path)
    old_digest = app.architecture_digest(PROJECT_ID)
    approval_path = project / ".archscope" / "approvals" / "current.json"
    approval_path.parent.mkdir(parents=True)
    approval_path.write_text(json.dumps({
        "architecture_digest": old_digest,
        "approved_at": "2026-09-20T00:00:00+00:00",
        "reviewer": "human",
        "proposal_id": "legacy-manual",
    }), encoding="utf-8")
    old_name = app.get_project(PROJECT_ID)["data"]["project"]["name"]
    approve_change(app, project, old_name, "新名称", "migrate-legacy")
    historical = app.get_project(PROJECT_ID, old_digest)
    assert historical["data"]["approval"]["status"] == "historical_approved"
    assert historical["data"]["approval"]["baseline"]["proposal_id"] == "legacy-manual"
    (project / "system.arch").write_text("invalid: [", encoding="utf-8")
    assert app.get_project(PROJECT_ID)["status"] == "error"
    assert app.get_project(PROJECT_ID, old_digest)["status"] == "ok"
