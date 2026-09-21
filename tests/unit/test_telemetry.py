from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from archscope.telemetry.events import MAX_PAYLOAD_BYTES, RuntimeEventWriter


ROOT = Path(__file__).resolve().parents[2]


def writer(path: Path) -> RuntimeEventWriter:
    return RuntimeEventWriter(path, project_id="mini_planner", run_id="run-1", arch_revision="arch-1", code_revision="code-1")


def test_runtime_event_redacts_credentials_and_unknown_object_without_repr(tmp_path: Path) -> None:
    event_path = tmp_path / "events.jsonl"

    class SensitiveObject:
        def __str__(self) -> str:
            return "SHOULD_NEVER_BE_STRINGIFIED"

    emitted = writer(event_path).emit("module.failed", module_id="data", payload={
        "api_key": "TEST_API_KEY_VALUE",
        "nested": {"password": "TEST_PASSWORD_VALUE", "message": "Bearer TEST_BEARER_VALUE"},
        "message": "api_key=TEST_INLINE_VALUE at " + "C:" + "\\private\\customer.txt and /tmp/customer-record.txt",
        "object": SensitiveObject(),
    })
    on_disk = event_path.read_text(encoding="utf-8")
    for secret in ("TEST_API_KEY_VALUE", "TEST_PASSWORD_VALUE", "TEST_BEARER_VALUE", "TEST_INLINE_VALUE", "customer.txt", "customer-record.txt", "SHOULD_NEVER_BE_STRINGIFIED"):
        assert secret not in on_disk
    assert emitted["payload"]["api_key"] == "<redacted>"
    assert emitted["payload"]["_redacted"] is True
    schema = json.loads((ROOT / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(json.loads(on_disk))


def test_runtime_event_has_final_byte_limit_and_visible_truncation(tmp_path: Path) -> None:
    event_path = tmp_path / "events.jsonl"
    huge = {f"branch-{index}": ["x" * 1000 for _ in range(100)] for index in range(100)}
    event = writer(event_path).emit("port.observed", module_id="data", payload={"summary": huge, "status": "observed"})
    assert len(json.dumps(event["payload"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert event["payload"]["_truncated"] is True
    assert event["payload"]["_reason"] == "payload_size_limit"
    assert event["payload"]["status"] == "observed"
    assert len(event_path.read_bytes()) < 10_000


def test_runtime_probe_cannot_forge_checker_origin(tmp_path: Path) -> None:
    event_path = tmp_path / "events.jsonl"
    probe = writer(event_path)
    with pytest.raises(ValueError, match="cannot impersonate"):
        probe.emit("check.finished", producer="checker", payload={"status": "PASS"})
    probe.close()
    assert event_path.read_text(encoding="utf-8") == ""
