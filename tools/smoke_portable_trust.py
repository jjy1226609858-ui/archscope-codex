#!/usr/bin/env python3
"""Exercise Ed25519 verification inside the frozen Windows runtime."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from archscope.service.trust import canonical_payload


def call(executable: Path, environment: dict[str, str], *arguments: str) -> dict:
    completed = subprocess.run([str(executable), *arguments], env=environment, capture_output=True, text=True, timeout=60)
    if completed.returncode != 0:
        raise AssertionError(f"frozen CLI failed: {completed.returncode}: {completed.stderr} {completed.stdout}")
    return json.loads(completed.stdout)


def signed_file(trust: Path, key: Ed25519PrivateKey, payload: dict) -> None:
    subject = "\0".join((payload["kind"], payload["project_id"], payload["architecture_digest"], payload.get("code_digest", ""), payload.get("verification_digest", "")))
    filename = f"{hashlib.sha256(subject.encode('utf-8')).hexdigest()}.json"
    folder = "architecture" if payload["kind"] == "architecture_approval" else "ci"
    path = trust / "attestations" / folder / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "payload": payload,
        "signature": base64.b64encode(key.sign(canonical_payload(payload))).decode("ascii"),
    }, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    plugin = args.plugin_root.resolve()
    data = args.data_root.resolve()
    trust = data.parent / f"{data.name}-trust"
    if data.exists() or trust.exists():
        raise SystemExit("Refusing existing smoke data or trust directory")
    trust.mkdir(parents=True)
    key = Ed25519PrivateKey.generate()
    (trust / "public_key.pem").write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    executable = plugin / "runtime" / "archscope.exe"
    resources = plugin / "resources"
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "ARCHSCOPE_REGISTRY", "ARCHSCOPE_PYTHON", "ARCHSCOPE_TRUST_ROOT"):
        environment.pop(name, None)
    environment["ARCHSCOPE_ROOT"] = str(resources)
    boot = call(executable, environment, "bootstrap", "--data-root", str(data), "--demo-root", str(resources / "examples" / "mini_planner"))
    registry = boot["registry"]
    current = call(executable, environment, "get-project", "mini_planner", "--registry", registry)
    arch_digest, code_digest = current["architecture_digest"], current["code_digest"]
    environment["ARCHSCOPE_TRUST_ROOT"] = str(trust)
    before = call(executable, environment, "check", "mini_planner", "--expected-architecture-digest", arch_digest, "--expected-code-digest", code_digest, "--registry", registry)
    initial_report = before["data"]["report"]
    assert initial_report["acceptance_status"] == "blocked", before
    stamp = datetime.now(UTC).isoformat()
    signed_file(trust, key, {
        "schema_version": "1", "kind": "architecture_approval", "project_id": "mini_planner",
        "architecture_digest": arch_digest, "approved_at": stamp, "reviewer": "portable-smoke-human",
    })
    signed_file(trust, key, {
        "schema_version": "1", "kind": "ci_pass", "project_id": "mini_planner",
        "architecture_digest": arch_digest, "code_digest": code_digest,
        "verification_digest": initial_report["verification_digest"], "checked_at": stamp,
        "checker_status": "PASS", "tests_status": "PASS", "workflow": "portable-smoke-ci",
    })
    after = call(executable, environment, "check", "mini_planner", "--expected-architecture-digest", arch_digest, "--expected-code-digest", code_digest, "--registry", registry)
    report = after["data"]["report"]
    assert report["status"] == "PASS" and report["acceptance_status"] == "eligible", after
    assert report["approval"]["protection"] == "external_signature", after
    assert report["ci_attestation"]["status"] == "PASS", after
    print(json.dumps({"status": "PASS", "version": call(executable, environment, "doctor", "--registry", registry)["data"]["tool_version"], "external_signature": "verified"}))


if __name__ == "__main__":
    main()
