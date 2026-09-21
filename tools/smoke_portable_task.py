#!/usr/bin/env python3
"""Repair an injected bug in an isolated demo; approvals are test fixtures, not host evidence."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from archscope.service import ArchScopeApplication


def packaged(executable: Path, env: dict[str, str], *args: str) -> dict:
    completed = subprocess.run(
        [str(executable), *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    return json.loads(completed.stdout)


def failed_run(executable: Path, env: dict[str, str], registry: str, digest: str) -> dict:
    completed = subprocess.run(
        [
            str(executable), "run-profile", "mini_planner", "demo-normal",
            "--expected-architecture-digest", digest,
            "--idempotency-key", "portable-repair-regression",
            "--registry", registry, "--wait-seconds", "30",
        ],
        env=env, capture_output=True, text=True, check=False, timeout=60,
    )
    assert completed.returncode == 4, (completed.returncode, completed.stdout, completed.stderr)
    result = json.loads(completed.stdout)
    assert result["status"] == "ok", result
    operation = result["data"]["operation"]
    assert operation["state"] == "failed" and operation["exit_code"] != 0, operation
    assert operation["event_count"] > 0 and operation["invalid_event_count"] == 0, operation
    return operation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    plugin = args.plugin_root.resolve()
    data = args.data_root.resolve()
    if data.exists():
        raise SystemExit(f"Refusing existing smoke data: {data}")
    executable = plugin / "runtime" / "archscope.exe"
    resources = plugin / "resources"
    env = dict(os.environ)
    for key in ("PYTHONPATH", "ARCHSCOPE_REGISTRY", "ARCHSCOPE_PYTHON"):
        env.pop(key, None)
    env["ARCHSCOPE_ROOT"] = str(resources)
    env["ARCHSCOPE_TARGET_PYTHON"] = str(Path(sys.executable).resolve())

    boot = packaged(executable, env, "bootstrap", "--data-root", str(data), "--demo-root", str(resources / "examples" / "mini_planner"))
    registry = boot["registry"]
    app = ArchScopeApplication(registry)
    project = app.get_project("mini_planner")
    digest = project["architecture_digest"]
    candidate = (data / "demos" / "mini_planner" / "system.arch").read_text(encoding="utf-8")
    proposal = app.propose_architecture("mini_planner", candidate, digest, "portable smoke fixture", "smoke-proposal")
    assert proposal["status"] == "ok", proposal
    proposal_data = proposal["data"]["proposal"]
    reviewed = app.review_proposal(
        "mini_planner", proposal_data["proposal_id"], digest,
        proposal_data["candidate_architecture_digest"], "我已审阅并批准此架构候选",
    )
    assert reviewed["status"] == "ok", reviewed
    source = data / "demos" / "mini_planner" / "src" / "demo" / "search" / "api.py"
    original = source.read_text(encoding="utf-8")
    insertion = '    if inject_error:\n        raise RuntimeError("Demonstration search failure")\n'
    assert original.count(insertion) == 1, "Demo search fixture changed"
    source.write_text(original.replace(
        insertion, insertion + '    raise RuntimeError("Injected repair-smoke regression")\n',
    ), encoding="utf-8")

    failure = failed_run(executable, env, registry, digest)
    failure_ref = f"run:{failure['operation_id']}"
    observed = app.read_evidence("mini_planner", failure_ref)
    assert observed["status"] == "ok", observed
    assert observed["data"]["evidence"]["value"]["state"] == "failed", observed
    current = app.get_project("mini_planner")
    check = app.check("mini_planner", current["architecture_digest"], current["code_digest"])
    assert check["status"] == "ok", check
    prepared = app.prepare_task(
        "mini_planner", "search", "Fix the injected search regression without changing interfaces",
        [failure_ref, *check["evidence_refs"]], current["architecture_digest"], current["code_digest"], "smoke-task",
    )
    assert prepared["status"] == "ok", prepared
    task = prepared["data"]["task"]
    approved = app.approve_task_scope(
        "mini_planner", task["task_id"], task["version"], "我已审阅并批准此任务范围",
    )
    assert approved["status"] == "ok", approved
    version = approved["data"]["task"]["version"]
    claimed = packaged(
        executable, env, "task-update", "mini_planner", task["task_id"], "claim",
        "--expected-version", str(version), "--actor-id", "portable-smoke", "--registry", registry,
    )
    assert claimed["status"] == "ok", claimed
    version = claimed["data"]["task"]["version"]
    assert source.read_text(encoding="utf-8") != original
    source.write_text(original, encoding="utf-8")
    completed = packaged(
        executable, env, "task-update", "mini_planner", task["task_id"], "declare_complete",
        "--expected-version", str(version), "--actor-id", "portable-smoke", "--registry", registry,
    )
    assert completed["status"] == "ok", completed
    result = completed["data"]["task"]
    assert result["state"] == "verified", result
    assert result["verification"]["tests"]["status"] == "PASS", result
    assert result["verification"]["changed_files"] == ["src/demo/search/api.py"], result
    recovered = packaged(
        executable, env, "run-profile", "mini_planner", "demo-normal",
        "--expected-architecture-digest", digest,
        "--idempotency-key", "portable-repair-recovered",
        "--registry", registry, "--wait-seconds", "30",
    )
    assert recovered["data"]["operation"]["state"] == "succeeded", recovered
    print(json.dumps({
        "status": "PASS", "fixture_only": True,
        "version": packaged(executable, env, "doctor", "--registry", registry)["data"]["tool_version"],
        "task_id": task["task_id"], "task_state": result["state"],
        "failed_run_id": failure["operation_id"], "failed_run_events": failure["event_count"],
        "changed_files": result["verification"]["changed_files"],
        "test_exit_code": result["verification"]["tests"]["exit_code"],
        "recovered_run_events": recovered["data"]["operation"]["event_count"],
    }))


if __name__ == "__main__":
    main()
