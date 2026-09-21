from __future__ import annotations

import base64
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from archscope.service import ArchScopeApplication
from archscope.service.trust import canonical_payload


ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "mini_planner"


def isolated_app(tmp_path: Path) -> tuple[ArchScopeApplication, Path]:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "mini_planner", project, ignore=shutil.ignore_patterns(".archscope", "__pycache__"))
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "project_id": PROJECT_ID, "root": "project", "arch": "system.arch", "control": ".archscope", "profiles": "run_profiles.json",
    }]}), encoding="utf-8")
    return ArchScopeApplication(registry), project


def make_trust_root(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey]:
    root = tmp_path / "operator-trust"
    root.mkdir()
    key = Ed25519PrivateKey.generate()
    root.joinpath("public_key.pem").write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    return root, key


def sign(root: Path, key: Ed25519PrivateKey, payload: dict) -> Path:
    subject = "\0".join((payload["kind"], payload["project_id"], payload["architecture_digest"], payload.get("code_digest", ""), payload.get("verification_digest", "")))
    subject_key = hashlib.sha256(subject.encode("utf-8")).hexdigest()
    if payload["kind"] == "architecture_approval":
        path = root / "attestations" / "architecture" / f"{subject_key}.json"
    else:
        path = root / "attestations" / "ci" / f"{subject_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "payload": payload,
        "signature": base64.b64encode(key.sign(canonical_payload(payload))).decode("ascii"),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def approval_payload(digest: str, *, project_id: str = PROJECT_ID) -> dict:
    return {
        "schema_version": "1", "kind": "architecture_approval", "project_id": project_id,
        "architecture_digest": digest, "approved_at": datetime.now(UTC).isoformat(), "reviewer": "external-human-review",
    }


def ci_payload(architecture_digest: str, code_digest: str, verification_digest: str) -> dict:
    return {
        "schema_version": "1", "kind": "ci_pass", "project_id": PROJECT_ID,
        "architecture_digest": architecture_digest, "code_digest": code_digest, "verification_digest": verification_digest,
        "checked_at": datetime.now(UTC).isoformat(), "checker_status": "PASS", "tests_status": "PASS",
        "workflow": "isolated-ci-fixture",
    }


def check(app: ArchScopeApplication) -> dict:
    project = app.get_project(PROJECT_ID)
    result = app.check(PROJECT_ID, project["architecture_digest"], project["code_digest"])
    assert result["status"] == "ok", result
    return result["data"]["report"]


def test_external_mode_fails_closed_until_both_signed_facts_match(tmp_path: Path, monkeypatch) -> None:
    app, project = isolated_app(tmp_path)
    digest = app.architecture_digest(PROJECT_ID)
    local = project / ".archscope" / "approvals" / "current.json"
    local.parent.mkdir(parents=True)
    local.write_text(json.dumps({
        "architecture_digest": digest, "approved_at": datetime.now(UTC).isoformat(),
        "reviewer": "human", "proposal_id": "local-only",
    }), encoding="utf-8")
    trust_root, key = make_trust_root(tmp_path)
    monkeypatch.setenv("ARCHSCOPE_TRUST_ROOT", str(trust_root))
    initial = check(app)
    assert initial["status"] == "PASS"
    assert initial["approval"]["status"] == "unapproved"
    assert initial["approval"]["protection"] == "external_signature"
    assert initial["acceptance_status"] == "blocked"

    arch_path = sign(trust_root, key, approval_payload(digest))
    approved_without_ci = check(app)
    assert approved_without_ci["approval"]["status"] == "approved"
    assert approved_without_ci["ci_attestation"]["status"] == "missing"
    assert approved_without_ci["acceptance_status"] == "blocked"

    ci_path = sign(trust_root, key, ci_payload(digest, approved_without_ci["code_digest"], approved_without_ci["verification_digest"]))
    eligible = check(app)
    assert eligible["acceptance_status"] == "eligible"
    assert eligible["ci_attestation"]["status"] == "PASS"
    advisory = app.check(PROJECT_ID, digest, eligible["code_digest"], strict=False)["data"]["report"]
    assert advisory["acceptance_status"] == "blocked"

    tampered = json.loads(ci_path.read_text(encoding="utf-8"))
    tampered["payload"]["workflow"] = "forged-workflow"
    ci_path.write_text(json.dumps(tampered), encoding="utf-8")
    invalid_ci = check(app)
    assert invalid_ci["ci_attestation"]["diagnostic_id"] == "TRUST_SIGNATURE_INVALID"
    assert invalid_ci["acceptance_status"] == "blocked"
    sign(trust_root, key, ci_payload(digest, eligible["code_digest"], eligible["verification_digest"]))

    tampered_arch = json.loads(arch_path.read_text(encoding="utf-8"))
    tampered_arch["payload"]["reviewer"] = "forged-reviewer"
    arch_path.write_text(json.dumps(tampered_arch), encoding="utf-8")
    invalid_approval = check(app)
    assert invalid_approval["approval"]["diagnostic_id"] == "TRUST_SIGNATURE_INVALID"
    assert invalid_approval["acceptance_status"] == "blocked"
    sign(trust_root, key, approval_payload(digest))

    test_file = project / "tests" / "test_normal.py"
    original_test = test_file.read_text(encoding="utf-8")
    test_file.write_text(original_test + "\n# changed test expectation source\n", encoding="utf-8")
    changed_tests = check(app)
    assert changed_tests["code_digest"] == eligible["code_digest"]
    assert changed_tests["verification_digest"] != eligible["verification_digest"]
    assert changed_tests["ci_attestation"]["status"] == "missing"
    test_file.write_text(original_test, encoding="utf-8")

    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# code drift\n", encoding="utf-8")
    drifted = check(app)
    assert drifted["status"] == "PASS"
    assert drifted["ci_attestation"]["status"] == "missing"
    assert drifted["acceptance_status"] == "blocked"


def test_invalid_or_project_local_trust_root_never_uses_local_approval(tmp_path: Path, monkeypatch) -> None:
    app, project = isolated_app(tmp_path)
    trust_root, key = make_trust_root(tmp_path)
    digest = app.architecture_digest(PROJECT_ID)
    expected_path = sign(trust_root, key, approval_payload(digest))
    wrong_project = approval_payload(digest, project_id="different-project")
    expected_path.write_text(json.dumps({
        "payload": wrong_project,
        "signature": base64.b64encode(key.sign(canonical_payload(wrong_project))).decode("ascii"),
    }), encoding="utf-8")
    monkeypatch.setenv("ARCHSCOPE_TRUST_ROOT", str(trust_root))
    wrong_subject = app.get_project(PROJECT_ID)["data"]["approval"]
    assert wrong_subject["status"] == "invalid"
    assert wrong_subject["diagnostic_id"] == "TRUST_SUBJECT_MISMATCH"
    monkeypatch.setenv("ARCHSCOPE_TRUST_ROOT", str(project / ".archscope"))
    invalid = app.get_project(PROJECT_ID)["data"]["approval"]
    assert invalid["status"] == "invalid"
    assert invalid["diagnostic_id"] == "TRUST_CONFIG_INVALID"


def test_task_completion_cannot_pass_without_current_signed_ci(tmp_path: Path, monkeypatch) -> None:
    app, project = isolated_app(tmp_path)
    trust_root, key = make_trust_root(tmp_path)
    monkeypatch.setenv("ARCHSCOPE_TRUST_ROOT", str(trust_root))
    current = app.get_project(PROJECT_ID)
    digest, code_digest = current["architecture_digest"], current["code_digest"]
    sign(trust_root, key, approval_payload(digest))
    checked = check(app)
    prepared = app.prepare_task(
        PROJECT_ID, "search", "验证外部 CI 阻断", [f"check:{checked['check_id']}"],
        digest, code_digest, "external-ci-task",
    )
    assert prepared["status"] == "ok", prepared
    task = prepared["data"]["task"]
    reviewed = app.approve_task_scope(PROJECT_ID, task["task_id"], task["version"], "我已审阅并批准此任务范围")
    assert reviewed["status"] == "ok", reviewed
    claimed = app.update_task(PROJECT_ID, task["task_id"], "claim", reviewed["data"]["task"]["version"], "codex-test")
    assert claimed["status"] == "ok", claimed
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# approved-scope edit\n", encoding="utf-8")
    completed = app.update_task(PROJECT_ID, task["task_id"], "declare_complete", claimed["data"]["task"]["version"], "codex-test", declaration="done")
    assert completed["status"] == "ok", completed
    result = completed["data"]["task"]
    assert result["state"] == "verification_blocked"
    assert result["verification"]["tests"]["status"] == "PASS"
    assert result["verification"]["check"]["status"] == "PASS"
    assert result["verification"]["ci_attestation_status"] == "missing"
    fresh_check = check(app)
    sign(trust_root, key, ci_payload(digest, fresh_check["code_digest"], fresh_check["verification_digest"]))
    reverification = app.update_task(PROJECT_ID, task["task_id"], "reverify", result["version"], "workbench")
    assert reverification["status"] == "ok", reverification
    verified = reverification["data"]["task"]
    assert verified["state"] == "verified"
    assert verified["verification"]["ci_attestation_status"] == "PASS"


def test_blocked_task_cannot_reverify_after_completion_snapshot_changes(tmp_path: Path, monkeypatch) -> None:
    app, project = isolated_app(tmp_path)
    trust_root, key = make_trust_root(tmp_path)
    monkeypatch.setenv("ARCHSCOPE_TRUST_ROOT", str(trust_root))
    current = app.get_project(PROJECT_ID)
    digest, code_digest = current["architecture_digest"], current["code_digest"]
    sign(trust_root, key, approval_payload(digest))
    checked = check(app)
    prepared = app.prepare_task(PROJECT_ID, "search", "完成后快照保护", [f"check:{checked['check_id']}"], digest, code_digest, "blocked-drift")
    task = prepared["data"]["task"]
    reviewed = app.approve_task_scope(PROJECT_ID, task["task_id"], task["version"], "我已审阅并批准此任务范围")["data"]["task"]
    claimed = app.update_task(PROJECT_ID, task["task_id"], "claim", reviewed["version"], "codex-test")["data"]["task"]
    completed = app.update_task(PROJECT_ID, task["task_id"], "declare_complete", claimed["version"], "codex-test")["data"]["task"]
    assert completed["state"] == "verification_blocked"
    assert completed["verification"]["snapshot_digest"]
    source = project / "src" / "demo" / "search" / "api.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# edit after declaration\n", encoding="utf-8")
    fresh_check = check(app)
    sign(trust_root, key, ci_payload(digest, fresh_check["code_digest"], fresh_check["verification_digest"]))
    rejected = app.update_task(PROJECT_ID, task["task_id"], "reverify", completed["version"], "workbench")
    assert rejected["diagnostics"][0]["diagnostic_id"] == "TASK_STALE"
    assert "Workspace snapshot changed" in rejected["diagnostics"][0]["message"]
    context = ArchScopeApplication(app.registry_path).resume_task(PROJECT_ID, task["task_id"])["data"]["context"]
    assert context["task"]["state"] == "needs_realign"
