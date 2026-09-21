#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import hashlib
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    raw = sys.stdin.buffer.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("hook input exceeds 1 MiB")
    event = json.loads(raw.decode("utf-8"))
    if not isinstance(event, dict):
        raise ValueError("hook input must be an object")
    session_id = str(event.get("session_id", ""))[:256]
    safe_session = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "unknown"
    if len(safe_session) > 80:
        safe_session = safe_session[:64] + "-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    data_root = Path(os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA") or Path(os.environ.get("TMPDIR", "/tmp")) / "archscope-plugin-data")
    hook_root = data_root / "hooks"
    hook_root.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "turn_id": str(event.get("turn_id", ""))[:256],
        "event": str(event.get("hook_event_name", ""))[:64],
        "tool_name": str(event.get("tool_name", ""))[:128],
        "tool_use_id": str(event.get("tool_use_id", ""))[:256],
        "cwd": str(event.get("cwd", ""))[:1024],
        "permission_mode": str(event.get("permission_mode", ""))[:64],
    }
    with (hook_root / f"{safe_session}.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary = hook_root / f"status.json.tmp.{os.getpid()}"
    temporary.write_text(json.dumps({"status": "active", "last_event": record["event"], "last_seen_at": record["recorded_at"], "session_id": session_id}), encoding="utf-8")
    temporary.replace(hook_root / "status.json")
    if record["event"] == "SessionStart":
        if re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", session_id):
            identity = f"For task leases in this session use actor_id 'codex-session:{session_id}'."
        else:
            identity = "Session identity is missing or malformed; do not claim task leases from this hook context."
        context = f"ArchScope lifecycle hook executed. {identity} Hook execution does not prove host trust; hooks only record lifecycle metadata and do not approve architecture, expand scope, or mark tasks verified."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ArchScope hook failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
