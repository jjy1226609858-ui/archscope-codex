from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProjectRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class RegisteredProject:
    project_id: str
    label: str
    root: Path
    arch_path: Path
    control_path: Path
    profile_path: Path
    python_path: Path | None = None


class ProjectRegistry:
    def __init__(self, registry_path: str | Path):
        self.path = Path(registry_path).expanduser().resolve()
        self._projects = self._load()

    def _load(self) -> dict[str, RegisteredProject]:
        try:
            payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectRegistryError(f"Cannot read project registry: {exc}") from exc

        entries = payload.get("projects")
        if not isinstance(entries, list):
            raise ProjectRegistryError("Project registry must contain a projects array")

        projects: dict[str, RegisteredProject] = {}
        base = self.path.parent
        for entry in entries:
            if not isinstance(entry, dict):
                raise ProjectRegistryError("Each projects entry must be an object")
            project_id = entry.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise ProjectRegistryError("project_id cannot be empty")
            if project_id in projects:
                raise ProjectRegistryError(f"Duplicate project_id: {project_id}")
            root = (base / entry.get("root", ".")).resolve()
            arch_path = (root / entry.get("arch", "system.arch")).resolve()
            control_path = (root / entry.get("control", ".archscope")).resolve()
            profile_path = (root / entry.get("profiles", "run_profiles.json")).resolve()
            python_value = entry.get("python")
            if python_value is not None and (not isinstance(python_value, str) or not python_value.strip()):
                raise ProjectRegistryError(f"Invalid target Python path: {project_id}")
            python_path = (root / python_value).resolve() if python_value else None
            if not arch_path.is_relative_to(root):
                raise ProjectRegistryError(f"Architecture file escapes the project root: {project_id}")
            if not control_path.is_relative_to(root):
                raise ProjectRegistryError(f"Control directory escapes the project root: {project_id}")
            if not profile_path.is_relative_to(root):
                raise ProjectRegistryError(f"Run profiles file escapes the project root: {project_id}")
            projects[project_id] = RegisteredProject(
                project_id=project_id,
                label=str(entry.get("label") or project_id),
                root=root,
                arch_path=arch_path,
                control_path=control_path,
                profile_path=profile_path,
                python_path=python_path,
            )
        return projects

    def get(self, project_id: str) -> RegisteredProject:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise ProjectRegistryError(f"PROJECT_NOT_REGISTERED: {project_id}") from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._projects))


def control_artifact_path(project: RegisteredProject, *parts: str) -> Path:
    """Resolve one plugin artifact while rejecting control-dir and nested symlink escapes."""
    project_root = project.root.resolve()
    control_root = project.control_path.resolve()
    if not control_root.is_relative_to(project_root):
        raise ProjectRegistryError("CONTROL_PATH_ESCAPE: Control directory escapes the project root")
    target = control_root.joinpath(*parts).resolve()
    if not target.is_relative_to(control_root):
        raise ProjectRegistryError("ARTIFACT_PATH_ESCAPE: Artifact path escapes the project control directory")
    return target
