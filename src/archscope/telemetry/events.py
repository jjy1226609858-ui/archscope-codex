from __future__ import annotations

import json
import math
import re
import threading
import uuid
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any


MAX_PAYLOAD_BYTES = 8192
_SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key|cookie", re.I)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_SECRET_ASSIGNMENT = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|credential)\s*[:=]\s*[^\s,;]+")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s,;]+")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9:/])/(?:[^/\s,;]+/)*[^/\s,;]+")


def _safe_text(value: str, state: dict[str, bool]) -> str:
    redacted = _PRIVATE_KEY.sub("<redacted>", value)
    redacted = _BEARER.sub("Bearer <redacted>", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    redacted = _OPENAI_KEY.sub("<redacted>", redacted)
    redacted = _AWS_KEY.sub("<redacted>", redacted)
    redacted = _WINDOWS_PATH.sub("<path>", redacted)
    redacted = _POSIX_PATH.sub("<path>", redacted)
    if redacted != value:
        state["redacted"] = True
    if len(redacted) > 240:
        state["truncated"] = True
        return redacted[:240]
    return redacted


def _bounded(value: Any, state: dict[str, bool], *, depth: int = 0) -> Any:
    if depth > 3:
        state["truncated"] = True
        return "<truncated>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "<non-finite>"
    if isinstance(value, str):
        return _safe_text(value, state)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in islice(value.items(), 17):
            if len(result) == 16:
                state["truncated"] = True
                break
            name = _safe_text(str(key), state)[:80]
            if _SENSITIVE_KEY.search(name):
                state["redacted"] = True
                result[name] = "<redacted>"
            else:
                result[name] = _bounded(item, state, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in islice(value, 17):
            if len(result) == 16:
                state["truncated"] = True
                break
            result.append(_bounded(item, state, depth=depth + 1))
        return result
    state["truncated"] = True
    return {"type": type(value).__name__}


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Runtime event payload must be an object")
    state = {"truncated": False, "redacted": False}
    bounded = _bounded(payload, state)
    if state["truncated"]:
        bounded["_truncated"] = True
    if state["redacted"]:
        bounded["_redacted"] = True
    encoded = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        return {
            "_truncated": True,
            "_redacted": state["redacted"],
            "_reason": "payload_size_limit",
            **{key: bounded[key] for key in ("status", "error_type") if key in bounded},
        }
    return bounded


class RuntimeEventWriter:
    """Append-only writer for small, redacted boundary summaries."""

    enabled = True

    def __init__(
        self,
        path: str | Path,
        *,
        project_id: str,
        run_id: str,
        arch_revision: str,
        code_revision: str,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.project_id = project_id
        self.run_id = run_id
        self.arch_revision = arch_revision
        self.code_revision = code_revision
        self._sequence = 0
        self._lock = threading.Lock()
        self._stream = self.path.open("a", encoding="utf-8", newline="\n")

    def close(self) -> None:
        with self._lock:
            self._stream.close()

    def emit(
        self,
        event_type: str,
        *,
        module_id: str | None = None,
        flow_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        payload: dict[str, Any] | None = None,
        producer: str = "runtime_sdk",
    ) -> dict[str, Any]:
        if producer != "runtime_sdk":
            raise ValueError("Runtime probe cannot impersonate another event producer")
        safe_payload = _safe_payload(payload if payload is not None else {})
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
            event = {
                "schema_version": "0.1",
                "event_id": uuid.uuid4().hex,
                "event_type": event_type,
                "stream": "runtime",
                "project_id": self.project_id,
                "arch_revision": self.arch_revision,
                "code_revision": self.code_revision,
                "occurred_at": datetime.now(UTC).isoformat(),
                "producer": "runtime_sdk",
                "producer_seq": sequence,
                "task_id": None,
                "run_id": self.run_id,
                "module_id": module_id,
                "flow_id": flow_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "payload": safe_payload,
            }
            self._stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._stream.flush()
            return event


class NullEventWriter:
    """Explicitly disable event persistence for probe-equivalence checks."""

    enabled = False

    def emit(self, event_type: str, **kwargs: Any) -> None:
        return None

    def close(self) -> None:
        return None
