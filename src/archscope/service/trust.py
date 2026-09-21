from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from archscope import __version__
from archscope.checking import CHECKER_VERSION
from archscope.service.registry import RegisteredProject


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ARCH_FIELDS = {"schema_version", "kind", "project_id", "architecture_digest", "approved_at", "reviewer"}
_CI_FIELDS = {"schema_version", "kind", "project_id", "architecture_digest", "code_digest", "verification_digest", "checked_at", "checker_status", "tests_status", "workflow"}


class TrustError(ValueError):
    def __init__(self, diagnostic_id: str, message: str):
        super().__init__(message)
        self.diagnostic_id = diagnostic_id


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrustError("TRUST_ATTESTATION_INVALID", f"Attestation contains a duplicate field: {key}")
        result[key] = value
    return result


def canonical_payload(payload: dict[str, Any]) -> bytes:
    """Stable v1 signing bytes shared with an external CI signer."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def compute_verification_digest(project: RegisteredProject, document: Any) -> str:
    """Bind CI evidence to the declared tests, profile config and checker build."""
    digest = hashlib.sha256()
    digest.update(f"archscope-ci-v1\0{__version__}\0{CHECKER_VERSION}\0".encode("utf-8"))
    selectors = {check["selector"] for check in document.model["checks"]}
    selectors.add(project.profile_path.relative_to(project.root).as_posix())
    for selector in sorted(selectors):
        path = (project.root / selector).resolve()
        if not path.is_relative_to(project.root):
            raise TrustError("VERIFICATION_PATH_ESCAPE", f"Verification input escapes the project root: {selector}")
        digest.update(selector.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        except OSError as exc:
            raise TrustError("VERIFICATION_INPUT_UNREADABLE", f"Verification input cannot be read: {selector}") from exc
        digest.update(b"\0")
    return digest.hexdigest()


class ExternalTrust:
    """Verify externally signed facts; this process never holds a signing key."""

    def __init__(self, project: RegisteredProject, root: Path):
        if not root.is_absolute():
            raise TrustError("TRUST_CONFIG_INVALID", "ARCHSCOPE_TRUST_ROOT must be an absolute path")
        if root.is_symlink():
            raise TrustError("TRUST_CONFIG_INVALID", "External trust directory must not be a symbolic link")
        try:
            self.root = root.resolve(strict=True)
        except OSError as exc:
            raise TrustError("TRUST_CONFIG_INVALID", f"External trust directory is unavailable: {exc}") from exc
        if not self.root.is_dir() or self.root.is_relative_to(project.root):
            raise TrustError("TRUST_CONFIG_INVALID", "External trust directory must be outside managed projects")
        self.project = project
        key_path = self.root / "public_key.pem"
        if key_path.is_symlink() or not key_path.is_file():
            raise TrustError("TRUST_KEY_INVALID", "External public key is missing or is a symbolic link")
        try:
            key_bytes = key_path.read_bytes()
            if len(key_bytes) > 8192:
                raise ValueError("Public key file is too large")
            key = serialization.load_pem_public_key(key_bytes)
        except (OSError, ValueError, UnsupportedAlgorithm) as exc:
            raise TrustError("TRUST_KEY_INVALID", f"External public key cannot be read: {exc}") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise TrustError("TRUST_KEY_INVALID", "External public key must use Ed25519")
        self.key = key
        raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.key_fingerprint = hashlib.sha256(raw).hexdigest()

    @classmethod
    def from_environment(cls, project: RegisteredProject) -> ExternalTrust | None:
        if "ARCHSCOPE_TRUST_ROOT" not in os.environ:
            return None
        value = os.environ["ARCHSCOPE_TRUST_ROOT"].strip()
        if not value:
            raise TrustError("TRUST_CONFIG_INVALID", "ARCHSCOPE_TRUST_ROOT is empty")
        return cls(project, Path(value).expanduser())

    def _record_path(self, kind: str, architecture_digest: str, code_digest: str | None = None, verification_digest: str | None = None) -> Path:
        if not _DIGEST.fullmatch(architecture_digest) or (code_digest is not None and not _DIGEST.fullmatch(code_digest)) or (verification_digest is not None and not _DIGEST.fullmatch(verification_digest)):
            raise TrustError("TRUST_SUBJECT_INVALID", "Attestation digest is invalid")
        subject = "\0".join((kind, self.project.project_id, architecture_digest, code_digest or "", verification_digest or ""))
        subject_key = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        if kind == "architecture_approval":
            return self.root / "attestations" / "architecture" / f"{subject_key}.json"
        return self.root / "attestations" / "ci" / f"{subject_key}.json"

    def _verify(self, path: Path, *, kind: str, architecture_digest: str, code_digest: str | None = None, verification_digest: str | None = None) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise TrustError("TRUST_ATTESTATION_MISSING", f"External attestation is missing: {kind}")
        if not path.resolve().is_relative_to(self.root):
            raise TrustError("TRUST_ATTESTATION_INVALID", "Attestation path escapes the trust directory")
        try:
            raw = path.read_bytes()
            if len(raw) > 32768:
                raise ValueError("Attestation is too large")
            record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, TrustError):
                raise
            raise TrustError("TRUST_ATTESTATION_INVALID", f"Cannot parse attestation: {exc}") from exc
        fields = _ARCH_FIELDS if kind == "architecture_approval" else _CI_FIELDS
        if not isinstance(record, dict) or set(record) != {"payload", "signature"}:
            raise TrustError("TRUST_ATTESTATION_INVALID", "Attestation must contain only payload and signature")
        payload = record["payload"]
        if not isinstance(payload, dict) or set(payload) != fields:
            raise TrustError("TRUST_ATTESTATION_INVALID", "Signed payload fields do not match the v1 contract")
        if payload.get("schema_version") != "1" or payload.get("kind") != kind or payload.get("project_id") != self.project.project_id:
            raise TrustError("TRUST_SUBJECT_MISMATCH", "Attestation kind or project does not match")
        if payload.get("architecture_digest") != architecture_digest or (code_digest is not None and payload.get("code_digest") != code_digest) or (verification_digest is not None and payload.get("verification_digest") != verification_digest):
            raise TrustError("TRUST_SUBJECT_MISMATCH", "Attestation architecture, code, or verification-input digest does not match")
        timestamp = payload.get("approved_at" if kind == "architecture_approval" else "checked_at")
        try:
            instant = datetime.fromisoformat(timestamp)
            if instant.tzinfo is None:
                raise ValueError("Timestamp must include a time zone")
        except (TypeError, ValueError) as exc:
            raise TrustError("TRUST_ATTESTATION_INVALID", f"Invalid attestation timestamp: {exc}") from exc
        identity = payload.get("reviewer" if kind == "architecture_approval" else "workflow")
        if not isinstance(identity, str) or not (1 <= len(identity) <= 200):
            raise TrustError("TRUST_ATTESTATION_INVALID", "Attestation reviewer or workflow ID is invalid")
        if kind == "ci_pass" and (payload.get("checker_status") != "PASS" or payload.get("tests_status") != "PASS"):
            raise TrustError("TRUST_ATTESTATION_INVALID", "CI attestation is not a complete passing result")
        try:
            if not isinstance(record["signature"], str):
                raise ValueError("Signature must be a Base64 string")
            signature = base64.b64decode(record["signature"], validate=True)
            if len(signature) != 64:
                raise ValueError("Invalid Ed25519 signature length")
            self.key.verify(signature, canonical_payload(payload))
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise TrustError("TRUST_SIGNATURE_INVALID", "External signature verification failed") from exc
        return payload

    def architecture_approval(self, digest: str) -> dict[str, Any]:
        payload = self._verify(self._record_path("architecture_approval", digest), kind="architecture_approval", architecture_digest=digest)
        return {"status": "approved", "protection": "external_signature", "baseline": payload, "key_fingerprint": self.key_fingerprint}

    def ci_pass(self, architecture_digest: str, code_digest: str, verification_digest: str) -> dict[str, Any]:
        payload = self._verify(self._record_path("ci_pass", architecture_digest, code_digest, verification_digest), kind="ci_pass", architecture_digest=architecture_digest, code_digest=code_digest, verification_digest=verification_digest)
        return {"status": "PASS", "protection": "external_signature", "attestation": payload, "key_fingerprint": self.key_fingerprint}
