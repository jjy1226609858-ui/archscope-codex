from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from archscope.service.registry import RegisteredProject


class TargetPythonError(ValueError):
    pass


def verify_target_python(candidate: Path) -> Path:
    """Reject Windows Store aliases and broken installs before recording a run."""
    resolved = candidate.expanduser().resolve()
    if not resolved.is_file():
        raise TargetPythonError(f"TARGET_PYTHON_NOT_FOUND: Interpreter file does not exist: {resolved}")
    try:
        probe = subprocess.run(
            [str(resolved), "-I", "-c", "import sys; print('ARCHSCOPE_PYTHON_OK:%d:%d' % sys.version_info[:2])"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TargetPythonError(
            f"TARGET_PYTHON_NOT_FOUND: Cannot execute target Python: {resolved} ({type(exc).__name__}). "
            "Configure the absolute path of a working Python 3.11+ interpreter. "
            "A Windows app execution alias is not an interpreter."
        ) from exc
    marker = probe.stdout.strip()
    if probe.returncode != 0 or not marker.startswith("ARCHSCOPE_PYTHON_OK:"):
        raise TargetPythonError(
            f"TARGET_PYTHON_NOT_FOUND: Target Python startup check failed: {resolved} "
            f"(exit code {probe.returncode}). Install or register a working Python 3.11+ "
            "interpreter; a Windows app execution alias may return only exit code 9009."
        )
    try:
        _, major, minor = marker.split(":")
        supported = (int(major), int(minor)) >= (3, 11)
    except ValueError as exc:
        raise TargetPythonError(f"TARGET_PYTHON_NOT_FOUND: Invalid interpreter version response: {resolved}") from exc
    if not supported:
        raise TargetPythonError(f"TARGET_PYTHON_NOT_FOUND: Target Python must be 3.11+; found {major}.{minor}: {resolved}")
    return resolved


def target_python(project: RegisteredProject) -> Path:
    """Resolve the target project's Python, never the frozen plugin executable."""
    configured = project.python_path or os.environ.get("ARCHSCOPE_TARGET_PYTHON")
    if configured:
        return verify_target_python(Path(configured))
    if not getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    failures: list[str] = []
    for command in ("python3", "python"):
        discovered = shutil.which(command)
        if discovered:
            try:
                return verify_target_python(Path(discovered))
            except TargetPythonError as exc:
                failures.append(str(exc))
    raise TargetPythonError(
        "TARGET_PYTHON_NOT_FOUND: No working target Python 3.11+ was found. "
        "Register a project with --python <absolute interpreter path>, or set "
        "ARCHSCOPE_TARGET_PYTHON and restart the plugin. The bundled ArchScope "
        "runtime and Windows app execution aliases cannot run the target project."
        + (f" Check detail: {failures[0]}" if failures else "")
    )
