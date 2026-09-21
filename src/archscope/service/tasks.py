from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from archscope.checking import compute_code_digest
from archscope.paths import target_sdk_path
from archscope.service.governance import ApprovalStore, CheckStore, GovernanceError
from archscope.service.interpreter import TargetPythonError, target_python

if TYPE_CHECKING:
    from archscope.service.registry import RegisteredProject
from archscope.service.registry import control_artifact_path


class TaskError(ValueError):
    def __init__(self, diagnostic_id: str, message: str):
        super().__init__(message)
        self.diagnostic_id = diagnostic_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TaskStore:
    def __init__(self, checks: CheckStore):
        self.checks = checks
        self._thread_lock = threading.RLock()

    @staticmethod
    def public_view(task: dict[str, Any]) -> dict[str, Any]:
        """Return the task contract without internal full-workspace snapshot hashes."""
        return {
            key: value for key, value in task.items()
            if key not in {"baseline_files", "request_fingerprint"}
        } | {"baseline_file_count": len(task.get("baseline_files", {}))}

    @staticmethod
    def _task_dir(project: RegisteredProject, task_id: str) -> Path:
        if not task_id or any(character not in "0123456789abcdef" for character in task_id):
            raise TaskError("TASK_NOT_FOUND", f"Unknown task: {task_id}")
        return control_artifact_path(project, "tasks", task_id)

    @contextmanager
    def _locked(self, task_dir: Path) -> Iterator[None]:
        lock_path = task_dir / ".task.lock"
        if not lock_path.resolve().is_relative_to(task_dir.resolve()):
            raise TaskError("TASK_PATH_ESCAPE", "Task lock file escapes the task directory")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _module_files(project: RegisteredProject, module: dict[str, Any]) -> list[str]:
        binding = module.get("binding")
        if not binding:
            return []
        result: set[str] = set()
        for pattern in binding["files"]:
            for value in glob.glob(str(project.root / pattern), recursive=True):
                path = Path(value).resolve()
                if path.is_file() and path.is_relative_to(project.root):
                    result.add(path.relative_to(project.root).as_posix())
        return sorted(result)

    @staticmethod
    def _snapshot(project: RegisteredProject, document: Any) -> dict[str, str]:
        paths: set[Path] = {project.arch_path, project.profile_path}
        for source_root in document.model["project"]["source_roots"]:
            root = (project.root / source_root).resolve()
            if root.is_dir() and root.is_relative_to(project.root):
                paths.update(path for path in root.rglob("*.py") if path.is_file())
        for check in document.model["checks"]:
            selector = (project.root / check["selector"]).resolve()
            if selector.is_relative_to(project.root):
                paths.add(selector)
        snapshot: dict[str, str] = {}
        for path in sorted(paths):
            resolved = path.resolve()
            if not resolved.is_relative_to(project.root):
                continue
            relative = resolved.relative_to(project.root).as_posix()
            snapshot[relative] = _sha256(resolved) if resolved.is_file() else "<missing>"
        return snapshot

    @staticmethod
    def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
        return sorted(path for path in before.keys() | after.keys() if before.get(path, "<missing>") != after.get(path, "<missing>"))

    @staticmethod
    def _snapshot_digest(snapshot: dict[str, str]) -> str:
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _scope_state(self, project: RegisteredProject, document: Any, task: dict[str, Any]) -> dict[str, Any]:
        current_snapshot = self._snapshot(project, document)
        changed_files = self._changed(task["baseline_files"], current_snapshot)
        module = document.modules_by_id.get(task["module_id"])
        allowed_now = set(self._module_files(project, module)) if module else set()
        allowed = set(task["allowed_files"]) | allowed_now
        protected = set(task["protected_files"])
        return {
            "snapshot": current_snapshot,
            "snapshot_digest": self._snapshot_digest(current_snapshot),
            "changed_files": changed_files,
            "out_of_scope_files": sorted(path for path in changed_files if path not in allowed or path in protected),
            "architecture_unchanged": task["architecture_digest"] == document.digest,
            "current_code_digest": compute_code_digest(project, document.model),
        }

    @staticmethod
    def _required_tests(document: Any, module_id: str) -> list[str]:
        direct = [check["selector"] for check in document.model["checks"] if check["required"] and module_id in check["modules"]]
        regression = [check["selector"] for check in document.model["checks"] if check["required"]]
        return list(dict.fromkeys([*direct, *regression]))

    def prepare(
        self,
        project: RegisteredProject,
        document: Any,
        *,
        module_id: str,
        objective: str,
        evidence_refs: list[str],
        expected_architecture_digest: str,
        expected_code_digest: str,
        idempotency_key: str,
        run_profiles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if expected_architecture_digest != document.digest:
            raise TaskError("REVISION_CONFLICT", "Architecture revision on which the task is based has changed")
        code_digest = compute_code_digest(project, document.model)
        if expected_code_digest != code_digest:
            raise TaskError("CODE_REVISION_CONFLICT", "Code snapshot on which the task is based has changed")
        if not objective or len(objective) > 2000:
            raise TaskError("TASK_OBJECTIVE_INVALID", "Task objective must contain 1–2000 characters")
        if not idempotency_key or len(idempotency_key) > 120:
            raise TaskError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must contain 1–120 characters")
        module = document.modules_by_id.get(module_id)
        if module is None:
            raise TaskError("MODULE_NOT_FOUND", f"Unknown module: {module_id}")
        if module["kind"] != "leaf":
            raise TaskError("TASK_SCOPE_INVALID", "Repair task must target a leaf module with a source binding")
        allowed_files = self._module_files(project, module)
        if not allowed_files:
            raise TaskError("TASK_SCOPE_NOT_READY", "Target module has no matched source files")
        allowed_patterns = list(module["binding"]["files"])
        protected_files = sorted({
            project.arch_path.relative_to(project.root).as_posix(),
            project.profile_path.relative_to(project.root).as_posix(),
            *(check["selector"] for check in document.model["checks"]),
        })
        fingerprint = hashlib.sha256(json.dumps({
            "project": project.project_id, "module": module_id, "objective": objective,
            "evidence": evidence_refs, "arch": document.digest, "code": code_digest,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        tasks_root = control_artifact_path(project, "tasks")
        tasks_root.mkdir(parents=True, exist_ok=True)
        with self._locked(tasks_root):
            for path in tasks_root.glob("*/task.json"):
                if not path.resolve().is_relative_to(tasks_root):
                    continue
                try:
                    existing = _read_json(path)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if existing.get("idempotency_key") != idempotency_key:
                    continue
                if existing.get("request_fingerprint") != fingerprint:
                    raise TaskError("IDEMPOTENCY_CONFLICT", "This idempotency key was used for a different task")
                return existing
            task_id = uuid.uuid4().hex
            task = {
                "task_id": task_id,
                "project_id": project.project_id,
                "version": 1,
                "state": "pending_scope_approval",
                "created_at": _now(),
                "updated_at": _now(),
                "module_id": module_id,
                "parent_module_id": module.get("parent"),
                "objective": objective,
                "evidence_refs": evidence_refs[:20],
                "architecture_digest": document.digest,
                "code_digest": code_digest,
                "module_ports": module["ports"],
                "allowed_files": allowed_files,
                "allowed_patterns": allowed_patterns,
                "protected_files": protected_files,
                "incoming_flows": [flow for flow in document.model["flows"] if flow["to"]["module"] == module_id],
                "outgoing_flows": [flow for flow in document.model["flows"] if flow["from"]["module"] == module_id],
                "required_tests": self._required_tests(document, module_id),
                "run_profiles": run_profiles or [],
                "source_roots": list(document.model["project"]["source_roots"]),
                "open_questions": document.model["project"].get("open_questions", []),
                "scope_approval": None,
                "lease": None,
                "baseline_files": self._snapshot(project, document),
                "completion_declaration": None,
                "verification": None,
                "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint,
            }
            task_dir = tasks_root / task_id
            task_dir.mkdir(parents=True, exist_ok=False)
            _write_json(task_dir / "task.json", task)
            return task

    def get(self, project: RegisteredProject, task_id: str) -> dict[str, Any]:
        path = control_artifact_path(project, "tasks", task_id, "task.json")
        try:
            return _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TaskError("TASK_NOT_FOUND", f"Unknown task: {task_id}") from exc

    def resume(self, project: RegisteredProject, document: Any, task_id: str) -> dict[str, Any]:
        """Rebuild a task's current context under its lock for a new session."""
        task_dir = self._task_dir(project, task_id)
        with self._locked(task_dir):
            task = self.get(project, task_id)
            scope = self._scope_state(project, document, task)
            lease_active = self._lease_active(task.get("lease"))
            expected = task.get("verification", {}).get("snapshot_digest") if task.get("verification") else None
            stale_reason = None
            if task["state"] in {"pending_scope_approval", "waiting_for_codex"}:
                if not scope["architecture_unchanged"] or scope["changed_files"]:
                    stale_reason = "Workspace snapshot changed before approval or claim"
            elif task["state"] == "in_progress":
                if not scope["architecture_unchanged"] or scope["out_of_scope_files"]:
                    stale_reason = "Architecture or out-of-scope files changed"
            elif task["state"] == "verification_blocked":
                if not expected or expected != scope["snapshot_digest"]:
                    stale_reason = "Workspace snapshot changed after completion declaration"
            if stale_reason:
                task.update(state="needs_realign", version=task["version"] + 1, updated_at=_now(), lease=None, realign_reason=stale_reason)
                _write_json(task_dir / "task.json", task)
            return {
                "task": task,
                "freshness": {
                    "snapshot_digest": scope["snapshot_digest"],
                    "verification_snapshot_digest": expected,
                    "changed_files": scope["changed_files"],
                    "out_of_scope_files": scope["out_of_scope_files"],
                    "architecture_unchanged": scope["architecture_unchanged"],
                    "current_code_digest": scope["current_code_digest"],
                    "lease_active": lease_active and not stale_reason,
                    "realign_reason": stale_reason or task.get("realign_reason"),
                },
            }

    def list(self, project: RegisteredProject, state: str | None = None) -> list[dict[str, Any]]:
        root = control_artifact_path(project, "tasks")
        if not root.is_dir():
            return []
        tasks: list[dict[str, Any]] = []
        for path in root.glob("*/task.json"):
            if not path.resolve().is_relative_to(root):
                continue
            try:
                task = _read_json(path)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if state is None or task.get("state") == state:
                tasks.append(task)
        return sorted(tasks, key=lambda item: item.get("created_at", ""), reverse=True)

    def approve_scope(
        self,
        project: RegisteredProject,
        document: Any,
        task_id: str,
        *,
        expected_version: int,
        acknowledgement: str,
    ) -> dict[str, Any]:
        if acknowledgement != "我已审阅并批准此任务范围":
            raise TaskError("TASK_SCOPE_CONFIRMATION_REQUIRED", "Task scope must be explicitly confirmed in the local review interface")
        task_dir = self._task_dir(project, task_id)
        with self._locked(task_dir):
            task = self.get(project, task_id)
            if task["version"] != expected_version:
                raise TaskError("TASK_VERSION_CONFLICT", "Task version has changed")
            if task["state"] != "pending_scope_approval":
                raise TaskError("TASK_STATE_CONFLICT", "Task is not awaiting scope approval")
            current_code = compute_code_digest(project, document.model)
            if task["architecture_digest"] != document.digest or task["code_digest"] != current_code:
                task.update(state="needs_realign", version=task["version"] + 1, updated_at=_now())
                _write_json(task_dir / "task.json", task)
                raise TaskError("TASK_STALE", "Architecture or code changed; task must be realigned")
            task.update(
                state="waiting_for_codex",
                version=task["version"] + 1,
                updated_at=_now(),
                scope_approval={"reviewer": "human", "approved_at": _now(), "protection": "collaborative_local"},
            )
            _write_json(task_dir / "task.json", task)
            return task

    @staticmethod
    def _lease_active(lease: dict[str, Any] | None) -> bool:
        if not lease:
            return False
        try:
            return datetime.fromisoformat(lease["expires_at"]) > datetime.now(UTC)
        except (KeyError, TypeError, ValueError):
            return False

    def update(
        self,
        project: RegisteredProject,
        document: Any,
        task_id: str,
        *,
        action: str,
        expected_version: int,
        actor_id: str,
        lease_seconds: int = 900,
        declaration: str | None = None,
        expected_snapshot_digest: str | None = None,
    ) -> dict[str, Any]:
        if not actor_id or len(actor_id) > 120:
            raise TaskError("ACTOR_ID_INVALID", "actor_id must contain 1–120 characters")
        task_dir = self._task_dir(project, task_id)
        with self._locked(task_dir):
            task = self.get(project, task_id)
            if task["version"] != expected_version:
                raise TaskError("TASK_VERSION_CONFLICT", "Task version has changed")
            if action == "claim":
                if task["state"] not in {"waiting_for_codex", "in_progress"}:
                    raise TaskError("APPROVAL_REQUIRED", "Task scope is not approved or the task cannot currently be claimed")
                if task["state"] == "in_progress" and self._lease_active(task.get("lease")):
                    if task["lease"].get("actor_id") == actor_id:
                        return task
                    raise TaskError("TASK_ALREADY_CLAIMED", "Task has already been claimed by another session")
                scope = self._scope_state(project, document, task)
                stale = (not scope["architecture_unchanged"] or bool(scope["out_of_scope_files"])) if task["state"] == "in_progress" else (not scope["architecture_unchanged"] or bool(scope["changed_files"]))
                if stale:
                    task.update(state="needs_realign", version=task["version"] + 1, updated_at=_now(), lease=None)
                    _write_json(task_dir / "task.json", task)
                    raise TaskError("TASK_STALE", "Architecture or task scope changed before claim")
                if task["state"] == "in_progress":
                    if not expected_snapshot_digest:
                        raise TaskError("TASK_RESUME_REQUIRED", "After the old session lease expires, resume task context and submit the current snapshot digest")
                    if expected_snapshot_digest != scope["snapshot_digest"]:
                        raise TaskError("TASK_SNAPSHOT_CONFLICT", "Workspace changed again after task recovery")
                if lease_seconds < 60 or lease_seconds > 3600:
                    raise TaskError("LEASE_INVALID", "lease_seconds must be between 60 and 3600")
                task.update(
                    state="in_progress",
                    version=task["version"] + 1,
                    updated_at=_now(),
                    lease={"actor_id": actor_id, "claimed_at": _now(), "expires_at": (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()},
                )
            elif action == "release":
                if task["state"] != "in_progress" or not task.get("lease") or task["lease"].get("actor_id") != actor_id:
                    raise TaskError("TASK_LEASE_REQUIRED", "Only the current claimant session can release this task")
                scope = self._scope_state(project, document, task)
                if not scope["architecture_unchanged"] or scope["out_of_scope_files"]:
                    task.update(state="needs_realign", version=task["version"] + 1, updated_at=_now(), lease=None, realign_reason="Architecture or out-of-scope files changed before release")
                else:
                    task.update(state="in_progress" if scope["changed_files"] else "waiting_for_codex", version=task["version"] + 1, updated_at=_now(), lease=None)
            elif action == "declare_complete":
                if task["state"] != "in_progress" or not task.get("lease") or task["lease"].get("actor_id") != actor_id:
                    raise TaskError("TASK_LEASE_REQUIRED", "Only the current claimant session can declare completion")
                task.update(
                    state="completion_declared",
                    version=task["version"] + 1,
                    updated_at=_now(),
                    completion_declaration={"actor_id": actor_id, "declared_at": _now(), "message": (declaration or "")[:2000]},
                    lease=None,
                )
                _write_json(task_dir / "task.json", task)
                task = self._verify(project, document, task)
                _write_json(task_dir / "task.json", task)
                return task
            elif action == "reverify":
                if task["state"] != "verification_blocked":
                    raise TaskError("TASK_STATE_CONFLICT", "Only tasks awaiting external evidence can be reverified")
                expected = (task.get("verification") or {}).get("snapshot_digest")
                if not expected or expected != self._snapshot_digest(self._snapshot(project, document)):
                    task.update(state="needs_realign", version=task["version"] + 1, updated_at=_now(), lease=None, realign_reason="Workspace snapshot changed after completion declaration")
                    _write_json(task_dir / "task.json", task)
                    raise TaskError("TASK_STALE", "Workspace snapshot changed after completion declaration; the old declaration cannot be reverified")
                task = self._verify(project, document, task)
                _write_json(task_dir / "task.json", task)
                return task
            else:
                raise TaskError("TASK_ACTION_INVALID", f"Unsupported task action: {action}")
            _write_json(task_dir / "task.json", task)
            return task

    def _verify(self, project: RegisteredProject, document: Any, task: dict[str, Any]) -> dict[str, Any]:
        scope = self._scope_state(project, document, task)
        changed_files = scope["changed_files"]
        out_of_scope = scope["out_of_scope_files"]
        architecture_unchanged = scope["architecture_unchanged"]
        current_code = scope["current_code_digest"]
        try:
            check_report = self.checks.run(
                project,
                document,
                expected_architecture_digest=document.digest,
                expected_code_digest=current_code,
                strict=True,
            )
        except GovernanceError as exc:
            check_report = {"status": "ERROR", "acceptance_status": "blocked", "diagnostics": [{"diagnostic_id": exc.diagnostic_id, "message": str(exc)}]}
        test_result = self._run_tests(project, task["required_tests"], task.get("source_roots", ["src"]))
        approval = ApprovalStore.status(project, document.digest)
        snapshot_stable = self._snapshot_digest(self._snapshot(project, document)) == scope["snapshot_digest"]
        verified = (
            not out_of_scope
            and architecture_unchanged
            and snapshot_stable
            and check_report.get("status") == "PASS"
            and check_report.get("acceptance_status") == "eligible"
            and test_result["status"] == "PASS"
            and approval["status"] == "approved"
        )
        blocked_only_by_approval = (
            not out_of_scope
            and architecture_unchanged
            and snapshot_stable
            and check_report.get("status") == "PASS"
            and test_result["status"] == "PASS"
            and (approval["status"] != "approved" or check_report.get("acceptance_status") != "eligible")
        )
        state = "verified" if verified else "verification_blocked" if blocked_only_by_approval else "verification_failed"
        task.update(
            state=state,
            version=task["version"] + 1,
            updated_at=_now(),
            verification={
                "verified_at": _now(),
                "architecture_unchanged": architecture_unchanged,
                "current_code_digest": current_code,
                "snapshot_digest": scope["snapshot_digest"],
                "snapshot_stable_during_verification": snapshot_stable,
                "changed_files": changed_files,
                "out_of_scope_files": out_of_scope,
                "check": {"check_id": check_report.get("check_id"), "status": check_report.get("status"), "acceptance_status": check_report.get("acceptance_status")},
                "tests": test_result,
                "approval_status": approval["status"],
                "ci_attestation_status": check_report.get("ci_attestation", {}).get("status", "not_reported"),
                "result": "PASS" if verified else "BLOCKED" if blocked_only_by_approval else "FAIL",
            },
        )
        return task

    @staticmethod
    def _run_tests(project: RegisteredProject, selectors: list[str], source_roots: list[str]) -> dict[str, Any]:
        missing = [selector for selector in selectors if not (project.root / selector).is_file()]
        if missing:
            return {"status": "NOT_RUN", "exit_code": None, "selectors": selectors, "missing": missing, "output": ""}
        try:
            python_executable = target_python(project)
        except TargetPythonError as exc:
            return {"status": "NOT_RUN", "exit_code": None, "selectors": selectors, "missing": [], "output": str(exc), "diagnostic_id": "TARGET_PYTHON_NOT_FOUND"}
        source_paths = [str((project.root / root).resolve()) for root in source_roots if (project.root / root).is_dir()]
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join([*source_paths, str(target_sdk_path())])}
        try:
            completed = subprocess.run(
                [str(python_executable), "-m", "pytest", "-q", *selectors],
                cwd=project.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                shell=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "ERROR", "exit_code": None, "selectors": selectors, "missing": [], "output": str(exc)[:8000]}
        output = (completed.stdout + "\n" + completed.stderr)[-8000:]
        if completed.returncode != 0 and "No module named pytest" in output:
            return {"status": "NOT_RUN", "exit_code": completed.returncode, "selectors": selectors, "missing": [], "output": output, "diagnostic_id": "PYTEST_NOT_AVAILABLE"}
        return {"status": "PASS" if completed.returncode == 0 else "FAIL", "exit_code": completed.returncode, "selectors": selectors, "missing": [], "output": output}
