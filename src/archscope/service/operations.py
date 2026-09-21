from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from archscope.paths import target_sdk_path
from archscope.service.interpreter import TargetPythonError, target_python
from archscope.service.registry import RegisteredProject, control_artifact_path


class OperationError(ValueError):
    def __init__(self, diagnostic_id: str, message: str):
        super().__init__(message)
        self.diagnostic_id = diagnostic_id


_RUNTIME_EVENT_TYPES = {
    "run.started", "run.finished", "module.started", "module.finished", "module.failed",
    "port.observed", "flow.transferred", "observation.lost", "events.dropped",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02)


class RunManager:
    """Runs only project-owned, predeclared profiles without invoking a shell."""

    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _run_root(project: RegisteredProject) -> Path:
        return control_artifact_path(project, "runs")

    @staticmethod
    def _operation_path(project: RegisteredProject, operation_id: str) -> Path:
        if not operation_id or any(character not in "0123456789abcdef" for character in operation_id):
            raise OperationError("OPERATION_NOT_FOUND", f"Unknown operation: {operation_id}")
        return control_artifact_path(project, "runs", operation_id, "operation.json")

    @staticmethod
    def _profiles(project: RegisteredProject) -> dict[str, dict[str, Any]]:
        path = project.profile_path
        try:
            payload = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperationError("RUN_PROFILES_INVALID", f"Cannot read run profiles: {exc}") from exc
        profiles = payload.get("profiles")
        if not isinstance(profiles, list):
            raise OperationError("RUN_PROFILES_INVALID", "Run profiles must contain a profiles array")
        result: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            if not isinstance(profile, dict) or not isinstance(profile.get("id"), str):
                raise OperationError("RUN_PROFILES_INVALID", "Invalid run profile entry")
            profile_id = profile["id"]
            if profile_id in result:
                raise OperationError("RUN_PROFILES_INVALID", f"Duplicate run profile ID: {profile_id}")
            if profile.get("module") != "demo.main":
                raise OperationError("RUN_PROFILES_INVALID", f"Unapproved entry module: {profile.get('module')}")
            if not isinstance(profile.get("observe", True), bool):
                raise OperationError("RUN_PROFILES_INVALID", f"observe must be a boolean: {profile_id}")
            scenario = (project.root / str(profile.get("scenario", ""))).resolve()
            if not scenario.is_relative_to(project.root) or not scenario.is_file():
                raise OperationError("RUN_PROFILES_INVALID", f"Scenario is outside the project or missing: {profile_id}")
            result[profile_id] = {**profile, "scenario_path": scenario}
        return result

    @staticmethod
    def profile_summaries(project: RegisteredProject) -> list[dict[str, str]]:
        return [
            {"id": profile_id, "label": str(profile.get("label") or profile_id)}
            for profile_id, profile in RunManager._profiles(project).items()
        ]

    @staticmethod
    def _code_digest(project: RegisteredProject) -> str:
        digest = hashlib.sha256()
        for source in sorted(project.root.glob("src/**/*.py")):
            if source.is_file():
                digest.update(source.relative_to(project.root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(source.read_bytes())
                digest.update(b"\0")
        return digest.hexdigest()

    def _find_idempotent(
        self,
        project: RegisteredProject,
        idempotency_key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        root = self._run_root(project)
        if not root.is_dir():
            return None
        for operation_path in root.glob("*/operation.json"):
            if not operation_path.resolve().is_relative_to(root):
                continue
            try:
                operation = _read_json(operation_path)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if operation.get("idempotency_key") != idempotency_key:
                continue
            if operation.get("request_fingerprint") != fingerprint:
                raise OperationError("IDEMPOTENCY_CONFLICT", "This idempotency key was used for a different run request")
            return operation
        return None

    def start(
        self,
        project: RegisteredProject,
        *,
        profile_id: str,
        architecture_digest: str,
        expected_architecture_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if architecture_digest != expected_architecture_digest:
            raise OperationError("REVISION_CONFLICT", "Requested architecture revision differs from the current revision")
        if not idempotency_key or len(idempotency_key) > 120:
            raise OperationError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must contain 1–120 characters")
        profiles = self._profiles(project)
        profile = profiles.get(profile_id)
        if profile is None:
            raise OperationError("RUN_PROFILE_NOT_FOUND", f"Unknown or unapproved run profile: {profile_id}")
        try:
            python_executable = target_python(project)
        except TargetPythonError as exc:
            raise OperationError("TARGET_PYTHON_NOT_FOUND", str(exc)) from exc
        try:
            scenario_bytes = profile["scenario_path"].read_bytes()
        except OSError as exc:
            raise OperationError("RUN_SCENARIO_UNREADABLE", f"Cannot read scenario file: {exc}") from exc
        if len(scenario_bytes) > 1_048_576:
            raise OperationError("RUN_SCENARIO_TOO_LARGE", "Scenario file must not exceed 1 MiB")
        scenario_digest = hashlib.sha256(scenario_bytes).hexdigest()
        code_digest = self._code_digest(project)
        profile_digest = hashlib.sha256(json.dumps({
            "id": profile_id,
            "module": profile["module"],
            "label": profile.get("label"),
            "scenario": str(profile["scenario_path"].relative_to(project.root)),
            "observe": profile.get("observe", True),
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        fingerprint = hashlib.sha256(json.dumps({
            "project": project.project_id,
            "architecture": architecture_digest,
            "code": code_digest,
            "profile": profile_digest,
            "scenario": scenario_digest,
            "python": str(python_executable),
        }, sort_keys=True).encode("utf-8")).hexdigest()
        with self._lock:
            previous = self._find_idempotent(project, idempotency_key, fingerprint)
            if previous is not None:
                if previous.get("state") in {"starting", "running", "cancelling"} and previous.get("operation_id") not in self._processes:
                    return {
                        **previous,
                        "state": "observation_lost",
                        "observation_coverage": "incomplete",
                        "diagnostic_id": "RUN_OWNER_LOST",
                        "exit_code": None,
                    }
                return previous

            operation_id = uuid.uuid4().hex
            run_id = operation_id
            run_dir = self._run_root(project) / operation_id
            run_dir.mkdir(parents=True, exist_ok=False)
            scenario_snapshot = run_dir / profile["scenario_path"].name
            scenario_snapshot.write_bytes(scenario_bytes)
            event_path = run_dir / "events.jsonl"
            result_path = run_dir / "result.json"
            stdout_path = run_dir / "stdout.log"
            stderr_path = run_dir / "stderr.log"
            operation_path = run_dir / "operation.json"
            operation = {
                "operation_id": operation_id,
                "run_id": run_id,
                "project_id": project.project_id,
                "profile_id": profile_id,
                "profile_label": str(profile.get("label") or profile_id),
                "observation_enabled": profile.get("observe", True),
                "state": "starting",
                "created_at": _now(),
                "updated_at": _now(),
                "started_at": None,
                "finished_at": None,
                "pid": None,
                "exit_code": None,
                "architecture_digest": architecture_digest,
                "code_digest": code_digest,
                "profile_digest": profile_digest,
                "scenario_digest": scenario_digest,
                "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint,
                "result": None,
            }
            _write_json(operation_path, operation)

            example_src = project.root / "src"
            python_path = os.pathsep.join([str(example_src), str(target_sdk_path())])
            environment = {**os.environ, "PYTHONPATH": python_path, "PYTHONDONTWRITEBYTECODE": "1"}
            command = [
                str(python_executable),
                "-m",
                "demo.main",
                "--scenario",
                str(scenario_snapshot),
                "--events",
                str(event_path),
                "--result",
                str(result_path),
                "--project-id",
                project.project_id,
                "--run-id",
                run_id,
                "--arch-revision",
                architecture_digest,
                "--code-revision",
                code_digest,
            ]
            if profile.get("observe") is False:
                command.append("--disable-observation")
            stdout_stream = stdout_path.open("w", encoding="utf-8")
            stderr_stream = stderr_path.open("w", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    command,
                    cwd=project.root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    text=True,
                    shell=False,
                )
            except OSError as exc:
                stdout_stream.close()
                stderr_stream.close()
                operation.update(
                    state="failed", updated_at=_now(), finished_at=_now(),
                    result={"status": "failed", "diagnostic_id": "RUN_LAUNCH_FAILED", "message": str(exc)},
                )
                _write_json(operation_path, operation)
                raise OperationError("RUN_LAUNCH_FAILED", f"Cannot launch target Python: {exc}") from exc
            operation.update(state="running", updated_at=_now(), started_at=_now(), pid=process.pid)
            _write_json(operation_path, operation)
            self._processes[operation_id] = process
            threading.Thread(
                target=self._monitor,
                args=(operation_id, operation_path, result_path, process, stdout_stream, stderr_stream),
                daemon=True,
                name=f"archscope-run-{operation_id[:8]}",
            ).start()
            return operation

    def _monitor(
        self,
        operation_id: str,
        operation_path: Path,
        result_path: Path,
        process: subprocess.Popen[str],
        stdout_stream: Any,
        stderr_stream: Any,
    ) -> None:
        exit_code = process.wait()
        stdout_stream.close()
        stderr_stream.close()
        with self._lock:
            operation = _read_json(operation_path)
            if operation.get("state") == "cancelling":
                state = "cancelled"
                result: dict[str, Any] = {"status": "cancelled"}
            elif result_path.is_file():
                try:
                    result = _read_json(result_path)
                    if not isinstance(result, dict):
                        raise ValueError("result is not an object")
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    result = {"status": "incomplete", "diagnostic_id": "RUN_RESULT_INVALID"}
                state = "observation_lost" if result.get("status") == "incomplete" else "succeeded" if exit_code == 0 and result.get("status") == "succeeded" else "failed"
            else:
                state = "observation_lost"
                result = {"status": "incomplete", "diagnostic_id": "RUN_RESULT_MISSING"}
            operation.update(
                state=state,
                result=result,
                exit_code=exit_code,
                updated_at=_now(),
                finished_at=_now(),
            )
            _write_json(operation_path, operation)
            self._processes.pop(operation_id, None)

    def get(
        self,
        project: RegisteredProject,
        operation_id: str,
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if cursor < 0 or limit < 1 or limit > 500:
            raise OperationError("EVENT_CURSOR_INVALID", "cursor must be nonnegative and limit must be between 1 and 500")
        path = self._operation_path(project, operation_id)
        try:
            with self._lock:
                operation = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperationError("OPERATION_NOT_FOUND", f"Unknown operation: {operation_id}") from exc
        if operation.get("state") in {"starting", "running", "cancelling"}:
            with self._lock:
                owns_run = operation_id in self._processes
            if not owns_run:
                operation = {
                    **operation,
                    "state": "observation_lost",
                    "observation_coverage": "incomplete",
                    "diagnostic_id": "RUN_OWNER_LOST",
                    "exit_code": None,
                }
        events: list[dict[str, Any]] = []
        event_path = control_artifact_path(project, "runs", operation_id, "events.jsonl")
        event_count = 0
        line_count = 0
        invalid_count = 0
        duplicate_count = 0
        loss_marker_count = 0
        next_cursor = cursor
        has_more = False
        seen_ids: set[str] = set()
        if event_path.is_file():
            with event_path.open(encoding="utf-8") as stream:
                for sequence, line in enumerate(stream):
                    line_count = sequence + 1
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeError):
                        invalid_count += 1
                        continue
                    if (
                        not isinstance(event, dict)
                        or not isinstance(event.get("event_id"), str)
                        or not event["event_id"]
                        or event.get("project_id") != project.project_id
                        or event.get("run_id") != operation_id
                        or event.get("producer") != "runtime_sdk"
                        or event.get("stream") != "runtime"
                        or not isinstance(event.get("event_type"), str)
                        or event.get("event_type") not in _RUNTIME_EVENT_TYPES
                        or type(event.get("producer_seq")) is not int
                        or event["producer_seq"] < 0
                        or not isinstance(event.get("payload"), dict)
                    ):
                        invalid_count += 1
                        continue
                    if event["event_id"] in seen_ids:
                        duplicate_count += 1
                        continue
                    seen_ids.add(event["event_id"])
                    event_count += 1
                    if event["event_type"] in {"observation.lost", "events.dropped"}:
                        loss_marker_count += 1
                    if sequence < cursor:
                        continue
                    if len(events) >= limit:
                        has_more = True
                        continue
                    events.append({"ingest_seq": sequence, **event})
                    next_cursor = sequence + 1
        if not has_more:
            next_cursor = max(cursor, line_count)
        if invalid_count or loss_marker_count:
            operation = {
                **operation,
                "diagnostic_id": "RUN_EVENTS_INVALID" if invalid_count else "RUN_EVENTS_DROPPED",
                "observation_coverage": "incomplete",
            }
            if operation.get("state") in {"succeeded", "failed", "cancelled"}:
                operation["state"] = "observation_lost"
        return {
            **operation,
            "events": events,
            "event_cursor": cursor,
            "next_cursor": next_cursor,
            "event_count": event_count,
            "event_line_count": line_count,
            "invalid_event_count": invalid_count,
            "duplicate_event_count": duplicate_count,
            "loss_marker_count": loss_marker_count,
            "has_more_events": has_more,
        }

    def get_for_overlay(self, project: RegisteredProject, operation_id: str, *, max_events: int = 20_000) -> dict[str, Any]:
        """Replay all available event pages for a graph without silently using only the first page."""
        cursor = 0
        collected: list[dict[str, Any]] = []
        while True:
            operation = self.get(project, operation_id, cursor=cursor, limit=500)
            collected.extend(operation["events"])
            if len(collected) > max_events or (len(collected) == max_events and operation["has_more_events"]):
                return {
                    **operation,
                    "events": [],
                    "state": "observation_lost",
                    "observation_coverage": "incomplete",
                    "diagnostic_id": "RUN_EVENT_OVERLAY_LIMIT",
                    "overlay_incomplete": True,
                }
            if not operation["has_more_events"]:
                if operation.get("observation_coverage") == "incomplete":
                    return {**operation, "events": [], "overlay_incomplete": True}
                return {**operation, "events": collected, "overlay_incomplete": False}
            if operation["next_cursor"] <= cursor:
                raise OperationError("EVENT_CURSOR_INVALID", "Event cursor did not advance; replay cannot continue safely")
            cursor = operation["next_cursor"]

    def cancel(self, project: RegisteredProject, operation_id: str) -> dict[str, Any]:
        path = self._operation_path(project, operation_id)
        with self._lock:
            try:
                operation = _read_json(path)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise OperationError("OPERATION_NOT_FOUND", f"Unknown operation: {operation_id}") from exc
            if operation["state"] in {"succeeded", "failed", "cancelled", "observation_lost"}:
                return operation
            process = self._processes.get(operation_id)
            if process is None or process.poll() is not None:
                raise OperationError("CANCEL_NOT_AVAILABLE", "The run process is not owned by this ArchScope session and cannot be cancelled safely")
            operation.update(state="cancelling", updated_at=_now())
            _write_json(path, operation)
            process.terminate()
        return operation
