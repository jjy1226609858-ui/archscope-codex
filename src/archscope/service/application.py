from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from archscope import API_VERSION, __version__
from archscope.checking import compute_code_digest
from archscope.model import ArchitectureError, load_architecture
from archscope.paths import default_registry_path, default_schema_path, repository_root
from archscope.service.registry import ProjectRegistry, ProjectRegistryError, RegisteredProject, control_artifact_path
from archscope.service.operations import OperationError, RunManager
from archscope.service.governance import ApprovalStore, CheckStore, GovernanceError, ProposalStore
from archscope.service.history import ArchitectureArchive, HistoryError
from archscope.service.tasks import TaskError, TaskStore


class ArchScopeApplication:
    """Single application service used by MCP, HTTP and CLI adapters."""

    def __init__(self, registry_path: str | Path | None = None, schema_path: str | Path | None = None):
        self.registry_path = Path(registry_path or default_registry_path()).resolve()
        self.schema_path = Path(schema_path or default_schema_path()).resolve()
        self.registry = ProjectRegistry(self.registry_path)
        self.registry_loaded_digest = hashlib.sha256(self.registry_path.read_bytes()).hexdigest()
        self.runs = RunManager()
        self.checks = CheckStore()
        self.proposals = ProposalStore(self.schema_path)
        self.tasks = TaskStore(self.checks)

    @staticmethod
    def _request_id() -> str:
        return uuid.uuid4().hex

    def _envelope(
        self,
        *,
        status: str,
        data: dict[str, Any],
        project_id: str | None = None,
        architecture_digest: str | None = None,
        code_digest: str | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "request_id": self._request_id(),
            "project_id": project_id,
            "status": status,
            "architecture_digest": architecture_digest,
            "code_digest": code_digest,
            "diagnostics": diagnostics or [],
            "evidence_refs": evidence_refs or [],
            "data": data,
        }

    def health(self, project_id: str | None = None) -> dict[str, Any]:
        project_state: dict[str, Any] | None = None
        status = "ok"
        diagnostics: list[dict[str, Any]] = []
        if project_id:
            project_result = self.get_project(project_id)
            project_state = {
                "status": project_result["status"],
                "architecture_digest": project_result.get("architecture_digest"),
                "approval": project_result.get("data", {}).get("approval"),
                "latest_ci_attestation": (project_result.get("data", {}).get("latest_check") or {}).get("ci_attestation"),
            }
            if project_result["status"] != "ok":
                status = "degraded"
                diagnostics.extend(project_result["diagnostics"])
        hook_status = self._hook_status()
        return self._envelope(
            status=status,
            project_id=project_id,
            diagnostics=diagnostics,
            data={
                "tool_version": __version__,
                "registry": {"registered_project_ids": list(self.registry.ids()), "loaded_digest": self.registry_loaded_digest},
                "capabilities": {
                    "archscope_health": "available",
                    "archscope_get_project": "available",
                    "archscope_get_module": "available",
                    "archscope_open_workbench": "available",
                    "archscope_run_profile": "available",
                    "archscope_get_operation": "available",
                    "archscope_cancel_run": "available",
                    "archscope_check": "available",
                    "archscope_propose_arch": "available",
                    "archscope_prepare_task": "available",
                    "archscope_get_task": "available",
                    "archscope_resume_task": "available",
                    "archscope_update_task": "available",
                    "archscope_read_evidence": "available",
                    "run_profiles": "available",
                    "checks": "available",
                    "external_signature_verification": "configured" if "ARCHSCOPE_TRUST_ROOT" in os.environ else "not_configured",
                    "task_repair": "available",
                    "hooks": hook_status["status"],
                    "embedded_ui": "not_tested",
                },
                "hook_status": hook_status,
                "project": project_state,
            },
        )

    def runtime_setup(self, project_id: str) -> dict[str, Any]:
        """Report interpreter discovery without executing any target program."""
        try:
            project = self.registry.get(project_id)
        except ProjectRegistryError as exc:
            return self._envelope(
                status="error", project_id=project_id,
                diagnostics=[{"diagnostic_id": "PROJECT_NOT_REGISTERED", "status": "FAIL", "message": str(exc)}],
                data={},
            )
        configured = project.python_path or os.environ.get("ARCHSCOPE_TARGET_PYTHON")
        if configured:
            source = "project" if project.python_path else "environment"
            state = "candidate_unverified" if Path(configured).expanduser().is_file() else "missing"
        elif not getattr(sys, "frozen", False):
            source, state = "development", "candidate_unverified"
        elif shutil.which("python3") or shutil.which("python"):
            source, state = "path", "candidate_unverified"
        else:
            source, state = "none", "missing"
        cli_prefix = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "archscope.cli"]
        return self._envelope(
            status="ok", project_id=project_id,
            data={
                "state": state, "source": source, "project_id": project_id,
                "registry": str(self.registry_path), "cli_prefix": cli_prefix,
                "message": "A target Python 3.11+ has not been verified. A registered path or PATH candidate is not proof that it can start."
                if state == "candidate_unverified" else "No target Python candidate was found. Configure a trusted Python 3.11+ interpreter before running a scenario.",
            },
        )

    @staticmethod
    def _hook_status() -> dict[str, Any]:
        data_root = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
        if data_root:
            status_path = Path(data_root).expanduser().resolve() / "hooks" / "status.json"
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                seen = datetime.fromisoformat(payload["last_seen_at"])
                age_seconds = max(0, int((datetime.now(UTC) - seen).total_seconds()))
                return {**payload, "status": "active" if age_seconds <= 86400 else "stale", "age_seconds": age_seconds, "trust": "execution_observed_origin_unverified"}
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                return {"status": "packaged_not_observed", "trust": "requires_user_review", "message": "Hooks are packaged, but this service has not observed them running; confirm trust in the host."}
        hook_config = repository_root() / "plugin" / "hooks" / "hooks.json"
        if hook_config.is_file():
            return {"status": "packaged_not_observed", "trust": "requires_user_review", "message": "Hooks are packaged; the user must review and trust their current definitions after installation."}
        return {"status": "not_configured", "trust": "none"}

    def _load_project(self, project_id: str) -> tuple[RegisteredProject, Any]:
        project = self.registry.get(project_id)
        document = load_architecture(project.arch_path, self.schema_path)
        if document.model["project"]["id"] != project_id:
            raise ProjectRegistryError(
                f"PROJECT_ID_MISMATCH: registry={project_id}, arch={document.model['project']['id']}"
            )
        return project, document

    def _load_revision(self, project_id: str, revision: str | None) -> tuple[RegisteredProject, Any, bool]:
        project = self.registry.get(project_id)
        if not revision:
            _, current = self._load_project(project_id)
            return project, current, False
        try:
            _, current = self._load_project(project_id)
        except ArchitectureError:
            current = None
        if current is not None and revision == current.digest:
            return project, current, False
        return project, ArchitectureArchive.load(project, revision, self.schema_path), True

    @staticmethod
    def _module_files(project: RegisteredProject, module: dict[str, Any]) -> list[str]:
        binding = module.get("binding")
        if not binding:
            return []
        files: set[str] = set()
        for pattern in binding.get("files", []):
            absolute_pattern = project.root / Path(pattern)
            for match in glob.glob(str(absolute_pattern), recursive=True):
                resolved = Path(match).resolve()
                if resolved.is_file() and resolved.is_relative_to(project.root):
                    files.add(resolved.relative_to(project.root).as_posix())
        return sorted(files)

    def _module_summary(self, project: RegisteredProject, module: dict[str, Any]) -> dict[str, Any]:
        matched_files = self._module_files(project, module)
        if module["kind"] == "composite":
            implementation = "structural"
        elif matched_files:
            implementation = "implemented"
        else:
            implementation = "not_ready"
        return {
            "id": module["id"],
            "name": module["name"],
            "kind": module["kind"],
            "parent": module.get("parent"),
            "implementation_status": implementation,
            "matched_files": matched_files,
            "verification_status": "NOT_RUN",
            "run_status": "NOT_RUN",
        }

    def _verification_overlay(self, project: RegisteredProject, document: Any) -> tuple[dict[str, str], dict[str, Any] | None, str]:
        code_digest = compute_code_digest(project, document.model)
        report = self.checks.latest(project)
        if report is None:
            return {}, None, code_digest
        if report.get("architecture_digest") != document.digest or report.get("code_digest") != code_digest:
            states = {module["id"]: "STALE" for module in document.model["modules"]}
            return states, {**report, "freshness": "STALE"}, code_digest
        return dict(report.get("module_states", {})), {**report, "freshness": "CURRENT"}, code_digest

    def get_project(self, project_id: str, revision: str | None = None) -> dict[str, Any]:
        try:
            project, document, historical = self._load_revision(project_id, revision)
        except ProjectRegistryError as exc:
            return self._envelope(
                status="error",
                project_id=project_id,
                diagnostics=[{"diagnostic_id": "PROJECT_NOT_REGISTERED", "status": "FAIL", "message": str(exc)}],
                data={},
            )
        except ArchitectureError as exc:
            return self._envelope(
                status="error",
                project_id=project_id,
                diagnostics=exc.diagnostics,
                data={},
            )
        except HistoryError as exc:
            return self._envelope(
                status="error",
                project_id=project_id,
                diagnostics=[{"diagnostic_id": exc.diagnostic_id, "status": "FAIL", "message": str(exc)}],
                data={},
            )

        if historical:
            verification, latest_check, code_digest = {}, None, None
        else:
            verification, latest_check, code_digest = self._verification_overlay(project, document)
        modules = [self._module_summary(project, module) for module in document.model["modules"]]
        for module in modules:
            if historical:
                module.update(implementation_status="historical_unknown", matched_files=[], verification_status="HISTORICAL_NOT_RECHECKED")
            else:
                module["verification_status"] = verification.get(module["id"], "NOT_RUN")
        if historical:
            try:
                approval = ApprovalStore.historical(project, document.digest)
            except HistoryError as exc:
                approval = {
                    "status": "historical_unapproved_or_missing",
                    "protection": "external_signature" if "ARCHSCOPE_TRUST_ROOT" in os.environ else "collaborative_local",
                    "baseline": None,
                    "diagnostic_id": exc.diagnostic_id,
                }
        else:
            approval = ApprovalStore.status(project, document.digest)
        revisions = ArchitectureArchive.list(project, self.schema_path)
        if historical:
            try:
                _, current_document = self._load_project(project_id)
            except ArchitectureError:
                current_document = None
        else:
            current_document = document
        if current_document is not None:
            revisions = [{"digest": current_document.digest, "name": current_document.model["project"]["name"], "historical": False}] + [
                {**item, "historical": True} for item in revisions if item["digest"] != current_document.digest
            ]
        else:
            revisions = [{**item, "historical": True} for item in revisions]
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=document.digest,
            code_digest=code_digest,
            evidence_refs=[f"arch:{document.digest}"],
            data={
                "project": document.model["project"],
                "summary": {
                    "module_count": len(modules),
                    "domain_count": len(document.model["domains"]),
                    "flow_count": len(document.model["flows"]),
                    "approval_status": approval["status"],
                    "evidence_coverage": "historical_architecture_only" if historical else "architecture_only",
                },
                "historical": historical,
                "architecture_revisions": revisions,
                "modules": modules,
                "run_profiles": [] if historical else self.runs.profile_summaries(project),
                "approval": approval,
                "latest_check": latest_check,
                "pending_proposals": [] if historical else self.proposals.list(project, "pending_review"),
                "tasks": [self.tasks.public_view(task) for task in self.tasks.list(project) if not historical or task.get("architecture_digest") == document.digest],
                "open_questions": document.model["project"].get("open_questions", []),
            },
        )

    def get_module(
        self,
        project_id: str,
        module_id: str,
        revision: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            project, document, historical = self._load_revision(project_id, revision)
        except ProjectRegistryError as exc:
            return self._envelope(status="error", project_id=project_id, diagnostics=[{"diagnostic_id": "PROJECT_NOT_REGISTERED", "status": "FAIL", "message": str(exc)}], data={})
        except ArchitectureError as exc:
            return self._envelope(status="error", project_id=project_id, diagnostics=exc.diagnostics, data={})
        except HistoryError as exc:
            return self._envelope(status="error", project_id=project_id, diagnostics=[{"diagnostic_id": exc.diagnostic_id, "status": "FAIL", "message": str(exc)}], data={})
        module = document.modules_by_id.get(module_id)
        if module is None:
            return self._envelope(status="error", project_id=project_id, architecture_digest=document.digest, diagnostics=[{"diagnostic_id": "MODULE_NOT_FOUND", "status": "FAIL", "message": f"Unknown module: {module_id}"}], data={})

        children = [item["id"] for item in document.model["modules"] if item.get("parent") == module_id]
        incoming = [flow for flow in document.model["flows"] if flow["to"]["module"] == module_id]
        outgoing = [flow for flow in document.model["flows"] if flow["from"]["module"] == module_id]
        summary = self._module_summary(project, module)
        if historical:
            latest_check, code_digest = None, None
            summary.update(implementation_status="historical_unknown", matched_files=[], verification_status="HISTORICAL_NOT_RECHECKED")
        else:
            verification, latest_check, code_digest = self._verification_overlay(project, document)
            summary["verification_status"] = verification.get(module_id, "NOT_RUN")
        runtime_summary: dict[str, Any] | None = None
        if run_id:
            try:
                operation = self.runs.get_for_overlay(project, run_id)
            except OperationError as exc:
                return self._envelope(status="error", project_id=project_id, architecture_digest=document.digest, diagnostics=[{"diagnostic_id": exc.diagnostic_id, "status": "FAIL", "message": str(exc)}], data={})
            if operation.get("architecture_digest") != document.digest:
                return self._envelope(status="error", project_id=project_id, architecture_digest=document.digest, diagnostics=[{"diagnostic_id": "RUN_REVISION_MISMATCH", "status": "FAIL", "message": "Run record does not belong to the requested architecture revision"}], data={})
            statuses, _, runtime = self._runtime_overlay(document, operation["events"])
            if operation.get("overlay_incomplete"):
                statuses = {item["id"]: "unknown" for item in document.model["modules"]}
                runtime = {}
            summary["run_status"] = statuses.get(module_id, "NOT_RUN")
            runtime_summary = runtime.get(module_id)
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=document.digest,
            code_digest=code_digest,
            evidence_refs=[f"arch:{document.digest}:module:{module_id}"],
            data={
                "module": module,
                "summary": summary,
                "runtime_summary": runtime_summary,
                "run_id": run_id,
                "historical": historical,
                "latest_check": latest_check,
                "children": children,
                "incoming_flows": incoming,
                "outgoing_flows": outgoing,
            },
        )

    @staticmethod
    def _runtime_overlay(document: Any, events: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
        module_status: dict[str, str] = {}
        flow_status: dict[str, str] = {}
        runtime: dict[str, dict[str, Any]] = {}
        ordered_events = sorted(events, key=lambda event: (event.get("producer_seq", event.get("ingest_seq", 0)), event.get("ingest_seq", 0)))
        for event in ordered_events:
            module_id = event.get("module_id")
            event_type = event.get("event_type")
            if module_id:
                item = runtime.setdefault(module_id, {"inputs": {}, "outputs": {}, "error": None, "event_count": 0})
                item["event_count"] += 1
                if event_type == "module.started":
                    if module_status.get(module_id) is None:
                        module_status[module_id] = "running"
                elif event_type == "module.finished":
                    previous = module_status.get(module_id)
                    if previous == "running":
                        module_status[module_id] = "succeeded"
                    elif previous is None:
                        module_status[module_id] = "unknown"
                elif event_type == "module.failed":
                    module_status[module_id] = "failed"
                    item["error"] = event.get("payload", {})
                elif event_type == "port.observed":
                    payload = event.get("payload", {})
                    direction = "inputs" if payload.get("direction") == "in" else "outputs"
                    item[direction][str(payload.get("port_id", "unknown"))] = payload.get("summary")
            flow_id = event.get("flow_id")
            if flow_id and event_type == "flow.transferred":
                flow_status[flow_id] = "succeeded"
        children_by_parent: dict[str, list[str]] = {}
        for module in document.model["modules"]:
            if module.get("parent"):
                children_by_parent.setdefault(module["parent"], []).append(module["id"])
        for parent, children in children_by_parent.items():
            states = [module_status.get(child, "NOT_RUN") for child in children]
            if "failed" in states:
                module_status[parent] = "failed"
            elif "running" in states:
                module_status[parent] = "running"
            elif states and all(state == "succeeded" for state in states):
                module_status[parent] = "succeeded"
            elif any(state == "succeeded" for state in states):
                module_status[parent] = "unknown"
        return module_status, flow_status, runtime

    def graph(self, project_id: str, revision: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        project_result = self.get_project(project_id, revision)
        if project_result["status"] != "ok":
            return project_result
        project, document, historical = self._load_revision(project_id, revision)
        summaries = {item["id"]: item for item in project_result["data"]["modules"]}
        module_status: dict[str, str] = {}
        flow_status: dict[str, str] = {}
        runtime: dict[str, dict[str, Any]] = {}
        operation: dict[str, Any] | None = None
        if run_id:
            try:
                operation = self.runs.get_for_overlay(project, run_id)
            except OperationError as exc:
                return self._envelope(status="error", project_id=project_id, architecture_digest=document.digest, diagnostics=[{"diagnostic_id": exc.diagnostic_id, "status": "FAIL", "message": str(exc)}], data={})
            if operation.get("architecture_digest") != document.digest:
                return self._envelope(status="error", project_id=project_id, architecture_digest=document.digest, diagnostics=[{"diagnostic_id": "RUN_REVISION_MISMATCH", "status": "FAIL", "message": "Run record does not belong to the requested architecture revision"}], data={})
            module_status, flow_status, runtime = self._runtime_overlay(document, operation["events"])
            if operation.get("overlay_incomplete"):
                module_status = {item["id"]: "unknown" for item in document.model["modules"]}
                flow_status = {item["id"]: "unknown" for item in document.model["flows"]}
                runtime = {}
        nodes = []
        for module in document.model["modules"]:
            nodes.append(
                {
                    "id": module["id"],
                    "name": module["name"],
                    "purpose": module["purpose"],
                    "kind": module["kind"],
                    "parent": module.get("parent"),
                    "ports": module["ports"],
                    "implementation_status": summaries[module["id"]]["implementation_status"],
                    "verification_status": summaries[module["id"]]["verification_status"],
                    "run_status": module_status.get(module["id"], "NOT_RUN"),
                    "runtime_summary": runtime.get(module["id"]),
                }
            )
        edges = [
            {
                "id": flow["id"],
                "source": flow["from"]["module"],
                "target": flow["to"]["module"],
                "source_port": flow["from"]["port"],
                "target_port": flow["to"]["port"],
                "kind": "declared_data_flow",
                "run_status": flow_status.get(flow["id"], "NOT_RUN"),
                "description": flow["description"],
            }
            for flow in document.model["flows"]
        ]
        project_result["data"] = {
            "project": project_result["data"]["project"],
            "run_profiles": project_result["data"]["run_profiles"],
            "approval": project_result["data"]["approval"],
            "historical": historical,
            "architecture_revisions": project_result["data"]["architecture_revisions"],
            "latest_check": project_result["data"]["latest_check"],
            "pending_proposals": project_result["data"]["pending_proposals"],
            "tasks": project_result["data"]["tasks"],
            "operation": operation,
            "nodes": nodes,
            "edges": edges,
            "domains": document.model["domains"],
            "legend": {
                "development": ["not_ready", "implemented", "structural"],
                "verification": ["NOT_RUN", "PASS", "FAIL", "UNVERIFIED", "STALE"],
                "run": ["NOT_RUN", "running", "succeeded", "failed", "unknown"],
            },
        }
        return project_result

    def check(
        self,
        project_id: str,
        expected_architecture_digest: str,
        expected_code_digest: str,
        strict: bool = True,
    ) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            ArchitectureArchive.save(project, document, self.schema_path)
            report = self.checks.run(
                project,
                document,
                expected_architecture_digest=expected_architecture_digest,
                expected_code_digest=expected_code_digest,
                strict=strict,
            )
        except (ProjectRegistryError, ArchitectureError, GovernanceError, HistoryError, ValueError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "CHECK_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=document.digest,
            code_digest=report["code_digest"],
            diagnostics=report["diagnostics"],
            evidence_refs=[f"check:{report['check_id']}"],
            data={"report": report},
        )

    def propose_architecture(
        self,
        project_id: str,
        candidate_text: str,
        expected_architecture_digest: str,
        rationale: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            ArchitectureArchive.save(project, document, self.schema_path)
            proposal = self.proposals.create(
                project,
                document,
                candidate_text=candidate_text,
                expected_architecture_digest=expected_architecture_digest,
                rationale=rationale,
                idempotency_key=idempotency_key,
            )
        except (ProjectRegistryError, ArchitectureError, GovernanceError, HistoryError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "PROPOSAL_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=document.digest,
            evidence_refs=[f"proposal:{proposal['proposal_id']}"],
            data={"proposal": proposal},
        )

    def get_architecture_editor(self, project_id: str) -> dict[str, Any]:
        """Expose only editable structure from the current validated .arch revision."""
        try:
            _, document = self._load_project(project_id)
        except (ProjectRegistryError, ArchitectureError) as exc:
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": "PROJECT_NOT_REGISTERED", "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(
            status="ok", project_id=project_id, architecture_digest=document.digest,
            data={
                "modules": document.model["modules"],
                "flows": document.model["flows"],
                "domains": document.model["domains"],
            },
        )

    def propose_visual_edit(
        self,
        project_id: str,
        modules: list[dict[str, Any]],
        flows: list[dict[str, Any]],
        expected_architecture_digest: str,
        rationale: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Replace only graph-editable fields, then use normal validation/review."""
        try:
            _, document = self._load_project(project_id)
        except (ProjectRegistryError, ArchitectureError) as exc:
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": "PROJECT_NOT_REGISTERED", "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        if document.digest != expected_architecture_digest:
            return self._envelope(
                status="error", project_id=project_id, architecture_digest=document.digest,
                diagnostics=[{"diagnostic_id": "REVISION_CONFLICT", "status": "FAIL", "message": "The formal architecture changed; reopen the visual editor"}], data={},
            )
        candidate = deepcopy(document.model)
        candidate["modules"] = modules
        candidate["flows"] = flows
        candidate_text = yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False)
        return self.propose_architecture(
            project_id, candidate_text, expected_architecture_digest, rationale, idempotency_key,
        )

    def list_proposals(self, project_id: str, state: str | None = None) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
        except (ProjectRegistryError, ArchitectureError) as exc:
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": "PROJECT_NOT_REGISTERED", "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=document.digest,
            data={"proposals": self.proposals.list(project, state)},
        )

    def review_proposal(
        self,
        project_id: str,
        proposal_id: str,
        expected_base_digest: str,
        expected_candidate_digest: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            proposal = self.proposals.approve(
                project,
                document,
                proposal_id=proposal_id,
                expected_base_digest=expected_base_digest,
                expected_candidate_digest=expected_candidate_digest,
                acknowledgement=acknowledgement,
            )
            _, updated_document = self._load_project(project_id)
        except (ProjectRegistryError, ArchitectureError, GovernanceError, HistoryError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "REVIEW_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=updated_document.digest,
            evidence_refs=[f"proposal:{proposal_id}", f"approval:{updated_document.digest}"],
            data={"proposal": proposal, "approval": ApprovalStore.status(project, updated_document.digest)},
        )

    def run_profile(
        self,
        project_id: str,
        profile_id: str,
        expected_architecture_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            ArchitectureArchive.save(project, document, self.schema_path)
            operation = self.runs.start(
                project,
                profile_id=profile_id,
                architecture_digest=document.digest,
                expected_architecture_digest=expected_architecture_digest,
                idempotency_key=idempotency_key,
            )
        except (ProjectRegistryError, ArchitectureError, OperationError, HistoryError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "RUN_START_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=document.digest,
            evidence_refs=[f"run:{operation['run_id']}"],
            data={"operation": operation},
        )

    def get_operation(self, project_id: str, operation_id: str, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        try:
            project = self.registry.get(project_id)
            operation = self.runs.get(project, operation_id, cursor=cursor, limit=limit)
            try:
                _, document = self._load_project(project_id)
            except ArchitectureError:
                document = None
        except (ProjectRegistryError, OperationError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "OPERATION_READ_FAILED")
            return self._envelope(status="error", project_id=project_id, diagnostics=[{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}], data={})
        operation_digest = operation.get("architecture_digest")
        if document is not None and operation_digest == document.digest:
            snapshot_status = "current"
        else:
            try:
                ArchitectureArchive.load(project, operation_digest, self.schema_path)
                snapshot_status = "available"
            except HistoryError as exc:
                snapshot_status = "missing_legacy_snapshot" if exc.diagnostic_id == "ARCHIVE_NOT_FOUND" else "invalid_snapshot"
        return self._envelope(status="ok", project_id=project_id, architecture_digest=operation_digest, evidence_refs=[f"run:{operation_id}"], data={"operation": operation, "architecture_snapshot_status": snapshot_status})

    def cancel_run(self, project_id: str, operation_id: str) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            operation = self.runs.cancel(project, operation_id)
        except (ProjectRegistryError, ArchitectureError, OperationError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "CANCEL_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(status="ok", project_id=project_id, architecture_digest=document.digest, evidence_refs=[f"run:{operation_id}"], data={"operation": operation})

    @staticmethod
    def _artifact_id(value: str, diagnostic_id: str = "EVIDENCE_REF_INVALID") -> str:
        if not value or any(character not in "0123456789abcdef" for character in value):
            raise TaskError(diagnostic_id, "Evidence reference contains an invalid identifier")
        return value

    def _resolve_evidence(self, project: RegisteredProject, document: Any, evidence_ref: str) -> dict[str, Any]:
        parts = evidence_ref.split(":")
        kind = parts[0] if parts else ""
        try:
            if kind == "run" and len(parts) == 2:
                operation_id = self._artifact_id(parts[1])
                return {"kind": kind, "ref": evidence_ref, "value": self.runs.get(project, operation_id, limit=200)}
            if kind == "check" and len(parts) == 2:
                check_id = self._artifact_id(parts[1])
                path = control_artifact_path(project, "checks", check_id, "report.json")
                return {"kind": kind, "ref": evidence_ref, "value": json.loads(path.read_text(encoding="utf-8"))}
            if kind == "proposal" and len(parts) == 2:
                proposal_id = self._artifact_id(parts[1])
                path = control_artifact_path(project, "proposals", proposal_id, "proposal.json")
                return {"kind": kind, "ref": evidence_ref, "value": json.loads(path.read_text(encoding="utf-8"))}
            if kind == "task" and len(parts) == 2:
                task_id = self._artifact_id(parts[1])
                return {"kind": kind, "ref": evidence_ref, "value": self.tasks.public_view(self.tasks.get(project, task_id))}
            if kind == "approval" and len(parts) == 2:
                digest = parts[1]
                self._artifact_id(digest)
                if document is not None and digest == document.digest:
                    approval = ApprovalStore.status(project, digest)
                    if approval["status"] != "approved":
                        raise TaskError("EVIDENCE_NOT_FOUND", "Current architecture has no valid approval record")
                else:
                    ArchitectureArchive.load(project, digest, self.schema_path)
                    approval = ApprovalStore.historical(project, digest)
                return {"kind": kind, "ref": evidence_ref, "value": approval}
            if kind == "arch" and len(parts) in {2, 4}:
                digest = parts[1]
                self._artifact_id(digest)
                archived = document if document is not None and digest == document.digest else ArchitectureArchive.load(project, digest, self.schema_path)
                if len(parts) == 4 and parts[2] == "module":
                    module = archived.modules_by_id.get(parts[3])
                    if module is None:
                        raise TaskError("EVIDENCE_NOT_FOUND", "Module in architecture evidence does not exist")
                    return {"kind": kind, "ref": evidence_ref, "value": {"module": module, "architecture_digest": digest}}
                if len(parts) == 2:
                    return {"kind": kind, "ref": evidence_ref, "value": {"project": archived.model["project"], "architecture_digest": digest}}
        except (OSError, UnicodeError, json.JSONDecodeError, OperationError, TaskError, HistoryError) as exc:
            if isinstance(exc, TaskError):
                raise
            diagnostic_id = getattr(exc, "diagnostic_id", "EVIDENCE_NOT_FOUND")
            raise TaskError(diagnostic_id, f"Cannot read evidence {evidence_ref}: {exc}") from exc
        raise TaskError("EVIDENCE_REF_INVALID", f"Unsupported evidence reference: {evidence_ref}")

    def prepare_task(
        self,
        project_id: str,
        module_id: str,
        objective: str,
        evidence_refs: list[str],
        expected_architecture_digest: str,
        expected_code_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            ArchitectureArchive.save(project, document, self.schema_path)
            if not evidence_refs or len(evidence_refs) > 20:
                raise TaskError("EVIDENCE_REQUIRED", "Task must include 1–20 traceable evidence references")
            for evidence_ref in evidence_refs:
                self._resolve_evidence(project, document, evidence_ref)
            task = self.tasks.prepare(
                project,
                document,
                module_id=module_id,
                objective=objective,
                evidence_refs=evidence_refs,
                expected_architecture_digest=expected_architecture_digest,
                expected_code_digest=expected_code_digest,
                idempotency_key=idempotency_key,
                run_profiles=self.runs.profile_summaries(project),
            )
        except (ProjectRegistryError, ArchitectureError, TaskError, HistoryError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "TASK_PREPARE_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(status="ok", project_id=project_id, architecture_digest=document.digest, code_digest=task["code_digest"], evidence_refs=[f"task:{task['task_id']}"], data={"task": self.tasks.public_view(task)})

    def get_task(self, project_id: str, task_id: str | None = None, state: str | None = None) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            data = {"task": self.tasks.public_view(self.tasks.get(project, task_id))} if task_id else {"tasks": [self.tasks.public_view(task) for task in self.tasks.list(project, state)]}
        except (ProjectRegistryError, ArchitectureError, TaskError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "TASK_READ_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(status="ok", project_id=project_id, architecture_digest=document.digest, data=data)

    def resume_task(self, project_id: str, task_id: str) -> dict[str, Any]:
        """Return a bounded task handoff packet rebuilt from durable state and current files."""
        try:
            project, document = self._load_project(project_id)
            resumed = self.tasks.resume(project, document, task_id)
            task = resumed["task"]
            evidence = []
            for ref in task.get("evidence_refs", []):
                try:
                    resolved = self._resolve_evidence(project, document, ref)
                    value = resolved.get("value", {})
                    evidence.append({
                        "ref": ref,
                        "kind": resolved["kind"],
                        "status": value.get("status") or value.get("state") or value.get("result"),
                        "available": True,
                    })
                except (TaskError, HistoryError) as exc:
                    evidence.append({"ref": ref, "available": False, "diagnostic_id": getattr(exc, "diagnostic_id", "EVIDENCE_UNAVAILABLE")})
            context = {
                "task": self.tasks.public_view(task),
                "freshness": resumed["freshness"],
                "evidence": evidence,
                "claimable": task["state"] == "waiting_for_codex" or (task["state"] == "in_progress" and not resumed["freshness"]["lease_active"]),
            }
        except (ProjectRegistryError, ArchitectureError, TaskError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "TASK_RESUME_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(status="ok", project_id=project_id, architecture_digest=document.digest, code_digest=resumed["freshness"]["current_code_digest"], evidence_refs=[f"task:{task_id}"], data={"context": context})

    def approve_task_scope(self, project_id: str, task_id: str, expected_version: int, acknowledgement: str) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            task = self.tasks.approve_scope(project, document, task_id, expected_version=expected_version, acknowledgement=acknowledgement)
        except (ProjectRegistryError, ArchitectureError, TaskError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "TASK_SCOPE_REVIEW_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(status="ok", project_id=project_id, architecture_digest=document.digest, evidence_refs=[f"task:{task_id}"], data={"task": self.tasks.public_view(task)})

    def update_task(
        self,
        project_id: str,
        task_id: str,
        action: str,
        expected_version: int,
        actor_id: str,
        lease_seconds: int = 900,
        declaration: str | None = None,
        expected_snapshot_digest: str | None = None,
    ) -> dict[str, Any]:
        try:
            project, document = self._load_project(project_id)
            task = self.tasks.update(
                project,
                document,
                task_id,
                action=action,
                expected_version=expected_version,
                actor_id=actor_id,
                lease_seconds=lease_seconds,
                declaration=declaration,
                expected_snapshot_digest=expected_snapshot_digest,
            )
        except (ProjectRegistryError, ArchitectureError, TaskError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "TASK_UPDATE_FAILED")
            diagnostics = exc.diagnostics if isinstance(exc, ArchitectureError) else [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}]
            return self._envelope(status="error", project_id=project_id, diagnostics=diagnostics, data={})
        return self._envelope(status="ok", project_id=project_id, architecture_digest=document.digest, evidence_refs=[f"task:{task_id}"], data={"task": self.tasks.public_view(task)})

    def read_evidence(self, project_id: str, evidence_ref: str) -> dict[str, Any]:
        try:
            project = self.registry.get(project_id)
            try:
                _, document = self._load_project(project_id)
            except ArchitectureError:
                document = None
            evidence = self._resolve_evidence(project, document, evidence_ref)
        except (ProjectRegistryError, TaskError) as exc:
            diagnostic_id = getattr(exc, "diagnostic_id", "EVIDENCE_READ_FAILED")
            return self._envelope(status="error", project_id=project_id, diagnostics=[{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": str(exc)}], data={})
        parts = evidence_ref.split(":")
        evidence_digest = parts[1] if parts[0] in {"arch", "approval"} else document.digest if document is not None else None
        if parts[0] == "run":
            evidence_digest = evidence["value"].get("architecture_digest", evidence_digest)
        return self._envelope(status="ok", project_id=project_id, architecture_digest=evidence_digest, evidence_refs=[evidence_ref], data={"evidence": evidence})

    def architecture_digest(self, project_id: str) -> str:
        _, document = self._load_project(project_id)
        return document.digest

    def registry_digest(self) -> str:
        return hashlib.sha256(self.registry_path.read_bytes()).hexdigest()
