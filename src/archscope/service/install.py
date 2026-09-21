from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from archscope.service.interpreter import TargetPythonError, verify_target_python


PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def bootstrap_data(data_root: str | Path, demo_root: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    source = Path(demo_root).expanduser().resolve()
    registry = root / "projects.json"
    target = root / "demos" / "mini_planner"
    if registry.is_file():
        return {"status": "existing", "registry": str(registry), "demo": str(target)}
    if not (source / "system.arch").is_file():
        raise ValueError(f"DEMO_NOT_FOUND: {source}")
    root.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".archscope", "__pycache__", "*.pyc"))
    _write_json(registry, {"projects": [{
        "project_id": "mini_planner",
        "label": "mini_planner architecture draft",
        "root": "demos/mini_planner",
        "arch": "system.arch",
        "control": ".archscope",
        "profiles": "run_profiles.json",
    }]})
    return {"status": "created", "registry": str(registry), "demo": str(target)}


def register_project(
    registry_path: str | Path,
    *,
    project_id: str,
    root: str | Path,
    arch: str = "system.arch",
    control: str = ".archscope",
    profiles: str = "run_profiles.json",
    label: str | None = None,
    python: str | Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError("project_id must start with a lowercase letter and contain only lowercase letters, digits, _ or -")
    registry = Path(registry_path).expanduser().resolve()
    project_root = Path(root).expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError(f"Project root does not exist: {project_root}")
    relative_values = {"arch": arch, "control": control, "profiles": profiles}
    for field, value in relative_values.items():
        candidate = (project_root / value).resolve()
        if Path(value).is_absolute() or not candidate.is_relative_to(project_root):
            raise ValueError(f"{field} must be a relative path inside the project root")
    if not (project_root / arch).is_file():
        raise ValueError(f"Architecture file does not exist: {project_root / arch}")
    if not (project_root / profiles).is_file():
        raise ValueError(f"Run profiles file does not exist: {project_root / profiles}")
    python_candidate = Path(python).expanduser() if python else None
    if python_candidate is not None and not python_candidate.is_absolute():
        raise ValueError("Target Python path must be absolute")
    python_path = python_candidate.resolve() if python_candidate is not None else None
    if python_path is not None:
        try:
            verify_target_python(python_path)
        except TargetPythonError as exc:
            raise ValueError(str(exc)) from exc
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {"projects": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
        raise ValueError("Invalid project registry format")
    entries = payload["projects"]
    existing = next((index for index, item in enumerate(entries) if item.get("project_id") == project_id), None)
    entry = {
        "project_id": project_id,
        "label": label or project_id,
        "root": str(project_root),
        "arch": arch,
        "control": control,
        "profiles": profiles,
    }
    if python_path is not None:
        entry["python"] = str(python_path)
    if existing is not None and not replace:
        raise ValueError(f"project_id is already registered: {project_id}")
    if existing is None:
        entries.append(entry)
        action = "created"
    else:
        if python_path is None and isinstance(entries[existing].get("python"), str):
            entry["python"] = entries[existing]["python"]
        entries[existing] = entry
        action = "replaced"
    _write_json(registry, payload)
    return {"status": action, "registry": str(registry), "project": entry}


def configure_target_python(registry_path: str | Path, *, project_id: str, python: str | Path) -> dict[str, Any]:
    """Change only a registered project's interpreter after a real startup check."""
    registry = Path(registry_path).expanduser().resolve()
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Project registry does not exist: {registry}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
        raise ValueError("Invalid project registry format")
    entries = payload["projects"]
    matches = [item for item in entries if isinstance(item, dict) and item.get("project_id") == project_id]
    if len(matches) != 1:
        raise ValueError(f"Project must be registered exactly once: {project_id}")
    python_candidate = Path(python).expanduser()
    if not python_candidate.is_absolute():
        raise ValueError("Target Python path must be absolute")
    python_path = python_candidate.resolve()
    try:
        verify_target_python(python_path)
    except TargetPythonError as exc:
        raise ValueError(str(exc)) from exc
    matches[0]["python"] = str(python_path)
    _write_json(registry, payload)
    return {"status": "updated", "registry": str(registry), "project_id": project_id, "python": str(python_path)}
