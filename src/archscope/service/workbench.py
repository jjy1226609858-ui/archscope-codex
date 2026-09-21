from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from archscope import __version__
from archscope.service.application import ArchScopeApplication
from archscope.service.registry import control_artifact_path


class WorkbenchManager:
    def __init__(self, application: ArchScopeApplication):
        self.application = application

    @staticmethod
    def _find_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _is_healthy(url: str, project_id: str, registry_digest: str) -> bool:
        try:
            address = urllib.parse.urlsplit(url)
            if (
                address.scheme != "http"
                or address.hostname != "127.0.0.1"
                or address.port is None
                or address.netloc != f"127.0.0.1:{address.port}"
                or address.path not in {"", "/"}
                or address.query
                or address.fragment
            ):
                return False
        except (TypeError, ValueError):
            return False
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=0.8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return (
                payload.get("project_id") == project_id
                and payload.get("status") in {"ok", "degraded"}
                and payload.get("data", {}).get("tool_version") == __version__
                and payload.get("data", {}).get("registry", {}).get("loaded_digest") == registry_digest
            )
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    @staticmethod
    def _serve_command(registry_path: Path, project_id: str, port: int) -> list[str]:
        command = [sys.executable]
        if getattr(sys, "frozen", False):
            command.append("serve")
        else:
            command.extend(["-m", "archscope.service.server"])
        command.extend([
            "--registry", str(registry_path),
            "--project-id", project_id,
            "--port", str(port),
        ])
        return command

    def open(self, project_id: str) -> dict[str, Any]:
        project = self.application.registry.get(project_id)
        control_dir = control_artifact_path(project, "services")
        control_dir.mkdir(parents=True, exist_ok=True)
        state_path = control_artifact_path(project, "services", "workbench.json")
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if self._is_healthy(state["url"], project_id, self.application.registry_loaded_digest):
                    return {"url": state["url"], "service_status": "reused", "pid": state.get("pid")}
            except (OSError, KeyError, json.JSONDecodeError):
                pass

        port = self._find_port()
        url = f"http://127.0.0.1:{port}"
        log_path = control_artifact_path(project, "services", "workbench.log")
        log_stream = log_path.open("ab")
        command = self._serve_command(self.application.registry_path, project_id, port)
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=log_stream,
            cwd=str(project.root),
            close_fds=True,
            creationflags=creationflags,
        )
        log_stream.close()
        for _ in range(30):
            if process.poll() is not None:
                break
            if self._is_healthy(url, project_id, self.application.registry_loaded_digest):
                state = {
                    "project_id": project_id,
                    "pid": process.pid,
                    "url": url,
                    "architecture_digest": self.application.architecture_digest(project_id),
                }
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                return {"url": url, "service_status": "started", "pid": process.pid}
            time.sleep(0.1)
        raise RuntimeError(f"Workbench failed to start; diagnostic log: {log_path}")
