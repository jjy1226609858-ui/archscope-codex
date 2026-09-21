from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import time
from pathlib import Path

from archscope import __version__
from archscope.model import ArchitectureError, load_architecture
from archscope.paths import default_registry_path, default_schema_path
from archscope.service.application import ArchScopeApplication
from archscope.service.install import bootstrap_data, configure_target_python, register_project
from archscope.service.registry import ProjectRegistryError
from archscope.service.server import main as serve_main


def _dump(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _application(registry_path: str) -> ArchScopeApplication:
    try:
        return ArchScopeApplication(registry_path)
    except (ProjectRegistryError, OSError) as exc:
        _dump({
            "status": "error",
            "diagnostic_id": "REGISTRY_NOT_READY",
            "registry": str(Path(registry_path).expanduser().resolve()),
            "message": str(exc),
            "hint": "Run bootstrap to initialize plugin data, or use --registry to select an existing project registry.",
        })
        raise SystemExit(3) from exc


def _wait_for_operation(
    app: ArchScopeApplication, project_id: str, operation_id: str, wait_seconds: float,
) -> dict:
    deadline = time.monotonic() + wait_seconds
    while True:
        result = app.get_operation(project_id, operation_id)
        if result["status"] != "ok":
            return result
        state = result["data"]["operation"]["state"]
        if state not in {"starting", "pending", "running", "cancelling"}:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                **result,
                "status": "error",
                "diagnostics": [{
                    "diagnostic_id": "RUN_WAIT_TIMEOUT", "status": "NOT_RUN",
                    "message": "Timed out waiting for the run. This CLI process will exit, so a later query may lose process ownership. Use a persistent MCP connection or the workbench for long runs.",
                }],
            }
        time.sleep(min(0.1, remaining))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archscope")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Inspect local implementation readiness")
    doctor.add_argument("--registry", default=str(default_registry_path()))
    validate = subparsers.add_parser("validate", help="Validate a .arch draft")
    validate.add_argument("--arch", required=True)
    validate.add_argument("--schema", default=str(default_schema_path()))
    project = subparsers.add_parser("get-project", help="Read a registered project")
    project.add_argument("project_id")
    project.add_argument("--registry", default=str(default_registry_path()))
    run = subparsers.add_parser("run-profile", help="Start one predeclared run profile")
    run.add_argument("project_id")
    run.add_argument("profile_id")
    run.add_argument("--expected-architecture-digest", required=True)
    run.add_argument("--idempotency-key", required=True)
    run.add_argument("--registry", default=str(default_registry_path()))
    run.add_argument("--wait-seconds", type=float, metavar="SECONDS", help="Wait for a terminal run result in this CLI process")
    operation = subparsers.add_parser("get-operation", help="Read a persisted run operation")
    operation.add_argument("project_id")
    operation.add_argument("operation_id")
    operation.add_argument("--registry", default=str(default_registry_path()))
    cancel = subparsers.add_parser("cancel-run", help="Cancel a run owned by this process")
    cancel.add_argument("project_id")
    cancel.add_argument("operation_id")
    cancel.add_argument("--registry", default=str(default_registry_path()))
    check = subparsers.add_parser("check", help="Run deterministic source-boundary checks")
    check.add_argument("project_id")
    check.add_argument("--expected-architecture-digest", required=True)
    check.add_argument("--expected-code-digest", required=True)
    check.add_argument("--advisory", action="store_true")
    check.add_argument("--registry", default=str(default_registry_path()))
    proposal = subparsers.add_parser("propose-arch", help="Save a validated architecture candidate for human review")
    proposal.add_argument("project_id")
    proposal.add_argument("--candidate", required=True)
    proposal.add_argument("--expected-architecture-digest", required=True)
    proposal.add_argument("--rationale", required=True)
    proposal.add_argument("--idempotency-key", required=True)
    proposal.add_argument("--registry", default=str(default_registry_path()))
    task_prepare = subparsers.add_parser("task-prepare", help="Prepare an evidence-bound repair task for human scope review")
    task_prepare.add_argument("project_id")
    task_prepare.add_argument("module_id")
    task_prepare.add_argument("--objective", required=True)
    task_prepare.add_argument("--evidence-ref", action="append", required=True)
    task_prepare.add_argument("--expected-architecture-digest", required=True)
    task_prepare.add_argument("--expected-code-digest", required=True)
    task_prepare.add_argument("--idempotency-key", required=True)
    task_prepare.add_argument("--registry", default=str(default_registry_path()))
    task_get = subparsers.add_parser("task-get", help="Read one task or list project tasks")
    task_get.add_argument("project_id")
    task_get.add_argument("task_id", nargs="?")
    task_get.add_argument("--state")
    task_get.add_argument("--registry", default=str(default_registry_path()))
    task_context = subparsers.add_parser("task-context", help="Recover a task handoff packet and current workspace snapshot")
    task_context.add_argument("project_id")
    task_context.add_argument("task_id")
    task_context.add_argument("--registry", default=str(default_registry_path()))
    task_update = subparsers.add_parser("task-update", help="Claim, release, declare completion or reverify blocked evidence")
    task_update.add_argument("project_id")
    task_update.add_argument("task_id")
    task_update.add_argument("action", choices=["claim", "release", "declare_complete", "reverify"])
    task_update.add_argument("--expected-version", required=True, type=int)
    task_update.add_argument("--actor-id", required=True)
    task_update.add_argument("--lease-seconds", default=900, type=int)
    task_update.add_argument("--declaration")
    task_update.add_argument("--expected-snapshot-digest")
    task_update.add_argument("--registry", default=str(default_registry_path()))
    evidence = subparsers.add_parser("read-evidence", help="Read a typed ArchScope evidence reference")
    evidence.add_argument("project_id")
    evidence.add_argument("evidence_ref")
    evidence.add_argument("--registry", default=str(default_registry_path()))
    bootstrap = subparsers.add_parser("bootstrap", help="Initialize writable plugin data and the bundled demo")
    bootstrap.add_argument("--data-root", required=True)
    bootstrap.add_argument("--demo-root", required=True)
    register = subparsers.add_parser("register-project", help="Add a local project to an ArchScope registry")
    register.add_argument("project_id")
    register.add_argument("--root", required=True)
    register.add_argument("--arch", default="system.arch")
    register.add_argument("--control", default=".archscope")
    register.add_argument("--profiles", default="run_profiles.json")
    register.add_argument("--label")
    register.add_argument("--python", help="Absolute path to the target project's Python interpreter")
    register.add_argument("--replace", action="store_true")
    register.add_argument("--registry", default=str(default_registry_path()))
    configure_python = subparsers.add_parser("configure-python", help="Set one registered project's trusted Python 3.11+ interpreter")
    configure_python.add_argument("project_id")
    configure_python.add_argument("--python", required=True, help="Absolute path to the target project's Python interpreter")
    configure_python.add_argument("--registry", default=str(default_registry_path()))
    subparsers.add_parser("mcp", help="Run the ArchScope STDIO MCP server")
    subparsers.add_parser("serve", help="Run the local browser workbench")
    return parser


def main() -> None:
    multiprocessing.freeze_support()
    parser = build_parser()
    args, remainder = parser.parse_known_args()
    if args.command == "serve":
        sys.argv = [sys.argv[0], *remainder]
        serve_main()
        return
    if args.command == "mcp":
        from archscope.mcp.server import main as mcp_main
        mcp_main()
        return
    if args.command == "bootstrap":
        try:
            result = bootstrap_data(args.data_root, args.demo_root)
        except (OSError, ValueError) as exc:
            _dump({"status": "error", "message": str(exc)})
            raise SystemExit(3)
        _dump(result)
        return
    if args.command == "register-project":
        try:
            result = register_project(
                args.registry,
                project_id=args.project_id,
                root=args.root,
                arch=args.arch,
                control=args.control,
                profiles=args.profiles,
                label=args.label,
                python=args.python,
                replace=args.replace,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _dump({"status": "error", "message": str(exc)})
            raise SystemExit(3)
        _dump(result)
        return
    if args.command == "configure-python":
        try:
            result = configure_target_python(args.registry, project_id=args.project_id, python=args.python)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _dump({"status": "error", "message": str(exc)})
            raise SystemExit(3)
        _dump(result)
        return
    if args.command == "doctor":
        app = _application(args.registry)
        _dump(app.health())
        return
    if args.command == "get-project":
        app = _application(args.registry)
        result = app.get_project(args.project_id)
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "run-profile":
        if args.wait_seconds is not None and not (0 < args.wait_seconds <= 3600):
            parser.error("--wait-seconds must be greater than 0 and at most 3600")
        app = _application(args.registry)
        result = app.run_profile(args.project_id, args.profile_id, args.expected_architecture_digest, args.idempotency_key)
        if result["status"] == "ok" and args.wait_seconds is not None:
            operation_id = result["data"]["operation"]["operation_id"]
            result = _wait_for_operation(app, args.project_id, operation_id, args.wait_seconds)
        _dump(result)
        if result["status"] != "ok":
            raise SystemExit(5 if any(item.get("diagnostic_id") == "RUN_WAIT_TIMEOUT" for item in result.get("diagnostics", [])) else 3)
        state = result["data"]["operation"]["state"]
        raise SystemExit(4 if args.wait_seconds is not None and state != "succeeded" else 0)
    if args.command == "get-operation":
        app = _application(args.registry)
        result = app.get_operation(args.project_id, args.operation_id)
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "cancel-run":
        app = _application(args.registry)
        result = app.cancel_run(args.project_id, args.operation_id)
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "check":
        app = _application(args.registry)
        result = app.check(args.project_id, args.expected_architecture_digest, args.expected_code_digest, not args.advisory)
        _dump(result)
        if result["status"] != "ok":
            raise SystemExit(3)
        raise SystemExit(0 if result["data"]["report"]["status"] == "PASS" else 4)
    if args.command == "propose-arch":
        app = _application(args.registry)
        candidate_text = Path(args.candidate).read_text(encoding="utf-8")
        result = app.propose_architecture(
            args.project_id,
            candidate_text,
            args.expected_architecture_digest,
            args.rationale,
            args.idempotency_key,
        )
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "task-prepare":
        app = _application(args.registry)
        result = app.prepare_task(
            args.project_id,
            args.module_id,
            args.objective,
            args.evidence_ref,
            args.expected_architecture_digest,
            args.expected_code_digest,
            args.idempotency_key,
        )
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "task-get":
        app = _application(args.registry)
        result = app.get_task(args.project_id, args.task_id, args.state)
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "task-context":
        app = _application(args.registry)
        result = app.resume_task(args.project_id, args.task_id)
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "task-update":
        app = _application(args.registry)
        result = app.update_task(
            args.project_id,
            args.task_id,
            args.action,
            args.expected_version,
            args.actor_id,
            args.lease_seconds,
            args.declaration,
            args.expected_snapshot_digest,
        )
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "read-evidence":
        app = _application(args.registry)
        result = app.read_evidence(args.project_id, args.evidence_ref)
        _dump(result)
        raise SystemExit(0 if result["status"] == "ok" else 3)
    if args.command == "validate":
        try:
            document = load_architecture(Path(args.arch), Path(args.schema))
        except ArchitectureError as exc:
            _dump({"status": "FAIL", "diagnostics": exc.diagnostics})
            raise SystemExit(2)
        _dump({"status": "PASS", "architecture_digest": document.digest, "diagnostics": []})


if __name__ == "__main__":
    main()
