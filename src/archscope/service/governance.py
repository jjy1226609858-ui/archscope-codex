from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from archscope.checking import ArchitectureChecker, compute_code_digest
from archscope.model import ArchitectureError, load_architecture
from archscope.service.history import ArchitectureArchive, HistoryError
from archscope.service.registry import ProjectRegistryError, RegisteredProject, control_artifact_path
from archscope.service.trust import ExternalTrust, TrustError, compute_verification_digest


class GovernanceError(ValueError):
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


class ApprovalStore:
    """Reads externally reviewed baselines; no ordinary application tool can create one."""

    @staticmethod
    def status(project: RegisteredProject, current_digest: str) -> dict[str, Any]:
        try:
            external = ExternalTrust.from_environment(project)
            if external is not None:
                return external.architecture_approval(current_digest)
        except TrustError as exc:
            return {
                "status": "unapproved" if exc.diagnostic_id == "TRUST_ATTESTATION_MISSING" else "invalid",
                "protection": "external_signature", "baseline": None,
                "diagnostic_id": exc.diagnostic_id, "message": str(exc),
            }
        try:
            path = control_artifact_path(project, "approvals", "current.json")
        except ProjectRegistryError as exc:
            return {"status": "invalid", "protection": "collaborative_local", "baseline": None, "message": str(exc)}
        if not path.is_file():
            return {"status": "unapproved", "protection": "collaborative_local", "baseline": None}
        try:
            baseline = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "invalid", "protection": "collaborative_local", "baseline": None, "message": str(exc)}
        required = {"architecture_digest", "approved_at", "reviewer", "proposal_id"}
        if not required.issubset(baseline) or baseline.get("reviewer") != "human":
            return {"status": "invalid", "protection": "collaborative_local", "baseline": baseline}
        status = "approved" if baseline["architecture_digest"] == current_digest else "changed_since_approval"
        return {"status": status, "protection": "collaborative_local", "baseline": baseline}

    @staticmethod
    def historical(project: RegisteredProject, digest: str) -> dict[str, Any]:
        try:
            external = ExternalTrust.from_environment(project)
            if external is not None:
                approval = external.architecture_approval(digest)
                return {**approval, "status": "historical_approved"}
        except TrustError as exc:
            raise HistoryError(exc.diagnostic_id, str(exc)) from exc
        try:
            root = control_artifact_path(project, "approvals", "history")
        except ProjectRegistryError as exc:
            raise HistoryError("APPROVAL_HISTORY_PATH_ESCAPE", str(exc)) from exc
        matches: list[dict[str, Any]] = []
        if root.is_dir():
            for path in root.glob("*.json"):
                if not path.resolve().is_relative_to(root):
                    continue
                try:
                    record = _read_json(path)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if record.get("architecture_digest") == digest and record.get("reviewer") == "human":
                    matches.append(record)
        if not matches:
            raise HistoryError("APPROVAL_HISTORY_NOT_FOUND", f"No approval record was saved for architecture revision: {digest}")
        latest = max(matches, key=lambda item: item.get("approved_at", ""))
        return {"status": "historical_approved", "protection": latest.get("protection", "collaborative_local"), "baseline": latest}

    @staticmethod
    def ci_status(project: RegisteredProject, architecture_digest: str, code_digest: str, verification_digest: str) -> dict[str, Any]:
        try:
            external = ExternalTrust.from_environment(project)
            if external is None:
                return {"status": "not_required", "protection": "collaborative_local"}
            return external.ci_pass(architecture_digest, code_digest, verification_digest)
        except TrustError as exc:
            return {
                "status": "missing" if exc.diagnostic_id == "TRUST_ATTESTATION_MISSING" else "invalid",
                "protection": "external_signature", "diagnostic_id": exc.diagnostic_id, "message": str(exc),
            }

    @staticmethod
    def preserve_current(project: RegisteredProject, current_digest: str) -> None:
        """Retain a pre-history approval before a reviewed revision replaces it."""
        current_path = control_artifact_path(project, "approvals", "current.json")
        if not current_path.is_file():
            return
        try:
            baseline = _read_json(current_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GovernanceError("APPROVAL_RECORD_INVALID", f"Cannot migrate existing approval record: {exc}") from exc
        if baseline.get("architecture_digest") != current_digest or baseline.get("reviewer") != "human":
            return
        try:
            ApprovalStore.historical(project, current_digest)
        except HistoryError:
            _write_json(control_artifact_path(project, "approvals", "history", f"legacy-{uuid.uuid4().hex}.json"), baseline)


class ProposalStore:
    def __init__(self, schema_path: Path):
        self.schema_path = schema_path

    @staticmethod
    def _diff(base: Any, candidate: Any) -> dict[str, Any]:
        def changes(key: str) -> dict[str, list[str]]:
            before = {item["id"]: item for item in base.model[key]}
            after = {item["id"]: item for item in candidate.model[key]}
            return {
                "added": sorted(after.keys() - before.keys()),
                "removed": sorted(before.keys() - after.keys()),
                "changed": sorted(item_id for item_id in before.keys() & after.keys() if before[item_id] != after[item_id]),
            }
        return {"modules": changes("modules"), "flows": changes("flows"), "domains": changes("domains")}

    def create(
        self,
        project: RegisteredProject,
        base_document: Any,
        *,
        candidate_text: str,
        expected_architecture_digest: str,
        rationale: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if expected_architecture_digest != base_document.digest:
            raise GovernanceError("REVISION_CONFLICT", "Architecture revision on which the candidate is based has changed")
        encoded = candidate_text.encode("utf-8")
        if not candidate_text or len(encoded) > 512 * 1024:
            raise GovernanceError("CANDIDATE_INVALID", "Candidate architecture must contain 1–524288 bytes")
        if not idempotency_key or len(idempotency_key) > 120:
            raise GovernanceError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must contain 1–120 characters")
        fingerprint = hashlib.sha256(
            expected_architecture_digest.encode() + b"\0" + encoded + b"\0" + rationale.encode("utf-8")
        ).hexdigest()
        root = control_artifact_path(project, "proposals")
        if root.is_dir():
            for metadata_path in root.glob("*/proposal.json"):
                if not metadata_path.resolve().is_relative_to(root):
                    continue
                try:
                    existing = _read_json(metadata_path)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if existing.get("idempotency_key") != idempotency_key:
                    continue
                if existing.get("request_fingerprint") != fingerprint:
                    raise GovernanceError("IDEMPOTENCY_CONFLICT", "This idempotency key was used for a different candidate")
                return existing

        proposal_id = uuid.uuid4().hex
        proposal_dir = root / proposal_id
        proposal_dir.mkdir(parents=True, exist_ok=False)
        candidate_path = proposal_dir / "candidate.arch"
        candidate_path.write_text(candidate_text, encoding="utf-8")
        try:
            candidate = load_architecture(candidate_path, self.schema_path)
        except ArchitectureError:
            candidate_path.unlink()
            proposal_dir.rmdir()
            raise
        if candidate.model["project"]["id"] != project.project_id:
            candidate_path.unlink()
            proposal_dir.rmdir()
            raise GovernanceError("PROJECT_ID_MISMATCH", "Candidate architecture project.id does not match the registered project")
        proposal = {
            "proposal_id": proposal_id,
            "project_id": project.project_id,
            "state": "pending_review",
            "created_at": _now(),
            "base_architecture_digest": base_document.digest,
            "candidate_architecture_digest": candidate.digest,
            "rationale": rationale[:2000],
            "diff": self._diff(base_document, candidate),
            "idempotency_key": idempotency_key,
            "request_fingerprint": fingerprint,
            "approval": None,
        }
        _write_json(proposal_dir / "proposal.json", proposal)
        return proposal

    @staticmethod
    def list(project: RegisteredProject, state: str | None = None) -> list[dict[str, Any]]:
        root = control_artifact_path(project, "proposals")
        proposals: list[dict[str, Any]] = []
        if not root.is_dir():
            return proposals
        for path in root.glob("*/proposal.json"):
            if not path.resolve().is_relative_to(root):
                continue
            try:
                item = _read_json(path)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if state is None or item.get("state") == state:
                proposals.append(item)
        return sorted(proposals, key=lambda item: item.get("created_at", ""), reverse=True)

    def approve(
        self,
        project: RegisteredProject,
        current_document: Any,
        *,
        proposal_id: str,
        expected_base_digest: str,
        expected_candidate_digest: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        if acknowledgement != "我已审阅并批准此架构候选":
            raise GovernanceError("REVIEW_CONFIRMATION_REQUIRED", "Candidate content must be explicitly confirmed in the local review interface")
        if not proposal_id or any(character not in "0123456789abcdef" for character in proposal_id):
            raise GovernanceError("PROPOSAL_NOT_FOUND", f"Unknown proposal: {proposal_id}")
        proposal_dir = control_artifact_path(project, "proposals", proposal_id)
        metadata_path = control_artifact_path(project, "proposals", proposal_id, "proposal.json")
        candidate_path = control_artifact_path(project, "proposals", proposal_id, "candidate.arch")
        try:
            proposal = _read_json(metadata_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GovernanceError("PROPOSAL_NOT_FOUND", f"Unknown proposal: {proposal_id}") from exc
        if proposal.get("state") == "approved":
            return proposal
        if proposal.get("state") != "pending_review":
            raise GovernanceError("PROPOSAL_NOT_REVIEWABLE", "Proposal cannot be approved in its current state")
        if expected_base_digest != current_document.digest or proposal.get("base_architecture_digest") != current_document.digest:
            raise GovernanceError("REVISION_CONFLICT", "Formal architecture changed; proposal must be reviewed again")
        candidate = load_architecture(candidate_path, self.schema_path)
        if candidate.digest != expected_candidate_digest or candidate.digest != proposal.get("candidate_architecture_digest"):
            raise GovernanceError("CANDIDATE_DIGEST_CONFLICT", "Candidate content no longer matches the reviewed digest")
        if candidate.model["project"]["id"] != project.project_id:
            raise GovernanceError("PROJECT_ID_MISMATCH", "Candidate architecture project.id does not match the registered project")
        ArchitectureArchive.save(project, current_document, self.schema_path)
        candidate_snapshot = ArchitectureArchive.save(project, candidate, self.schema_path)
        ApprovalStore.preserve_current(project, current_document.digest)
        target = project.arch_path.resolve()
        if not target.is_relative_to(project.root):
            raise GovernanceError("SOURCE_PATH_ESCAPE", "Formal architecture path escapes the project root")
        temporary = target.with_suffix(target.suffix + ".reviewed.tmp")
        temporary.write_text(candidate_snapshot.read_text(encoding="utf-8"), encoding="utf-8")
        temporary.replace(target)
        approval = {
            "architecture_digest": candidate.digest,
            "previous_architecture_digest": current_document.digest,
            "approved_at": _now(),
            "reviewer": "human",
            "proposal_id": proposal_id,
            "protection": "collaborative_local",
        }
        _write_json(control_artifact_path(project, "approvals", "current.json"), approval)
        _write_json(control_artifact_path(project, "approvals", "history", f"{proposal_id}.json"), approval)
        proposal.update(state="approved", approval=approval, reviewed_at=approval["approved_at"])
        _write_json(metadata_path, proposal)
        return proposal


class CheckStore:
    def run(
        self,
        project: RegisteredProject,
        document: Any,
        *,
        expected_architecture_digest: str,
        expected_code_digest: str,
        strict: bool,
    ) -> dict[str, Any]:
        if expected_architecture_digest != document.digest:
            raise GovernanceError("REVISION_CONFLICT", "Requested architecture revision differs from the current revision")
        code_digest = compute_code_digest(project, document.model)
        if expected_code_digest != code_digest:
            raise GovernanceError("CODE_REVISION_CONFLICT", "Requested code snapshot differs from the current workspace")
        checker_result = ArchitectureChecker(project, document).run(strict=strict)
        approval = ApprovalStore.status(project, document.digest)
        try:
            verification_digest = compute_verification_digest(project, document)
        except TrustError as exc:
            raise GovernanceError(exc.diagnostic_id, str(exc)) from exc
        ci_attestation = ApprovalStore.ci_status(project, document.digest, code_digest, verification_digest)
        acceptance_status = "eligible" if strict and approval["status"] == "approved" and checker_result["status"] == "PASS" and ci_attestation["status"] in {"PASS", "not_required"} else "blocked"
        check_id = uuid.uuid4().hex
        report = {
            "check_id": check_id,
            "project_id": project.project_id,
            "created_at": _now(),
            "architecture_digest": document.digest,
            "code_digest": code_digest,
            "verification_digest": verification_digest,
            "status": checker_result["status"],
            "acceptance_status": acceptance_status,
            "approval": approval,
            "ci_attestation": ci_attestation,
            **{key: value for key, value in checker_result.items() if key != "status"},
        }
        report_dir = control_artifact_path(project, "checks", check_id)
        _write_json(report_dir / "report.json", report)
        _write_json(control_artifact_path(project, "checks", "latest.json"), {"check_id": check_id})
        return report

    @staticmethod
    def latest(project: RegisteredProject) -> dict[str, Any] | None:
        try:
            latest_path = control_artifact_path(project, "checks", "latest.json")
        except ProjectRegistryError:
            return None
        if not latest_path.is_file():
            return None
        try:
            check_id = _read_json(latest_path)["check_id"]
            if not isinstance(check_id, str) or any(character not in "0123456789abcdef" for character in check_id):
                return None
            return _read_json(control_artifact_path(project, "checks", check_id, "report.json"))
        except (OSError, KeyError, UnicodeError, json.JSONDecodeError, ProjectRegistryError):
            return None
