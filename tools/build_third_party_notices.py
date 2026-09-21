"""Collect third-party license texts for a Windows ArchScope plugin package.

The generated inventory describes installed distributions used by the frozen
service and packages bundled into the production browser UI. It fails closed
when a component lacks an inspectable license text.
"""

from __future__ import annotations

import argparse
from collections import deque
from importlib import metadata
from pathlib import Path
import re
import shutil
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


RUNTIME_ROOTS = (
    "cryptography", "fastapi", "jsonschema", "mcp", "PyYAML", "uvicorn",
    # Build/runtime components copied into the frozen executable:
    "pyinstaller", "pywin32", "setuptools",
)


def python_distributions() -> list[metadata.Distribution]:
    pending = deque(RUNTIME_ROOTS)
    found: dict[str, metadata.Distribution] = {}
    while pending:
        requested = pending.popleft()
        key = canonicalize_name(requested)
        if key in found:
            continue
        dist = metadata.distribution(requested)
        found[key] = dist
        for requirement_text in dist.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            pending.append(requirement.name)
    return sorted(found.values(), key=lambda dist: canonicalize_name(dist.metadata["Name"]))


def license_files_for_distribution(dist: metadata.Distribution) -> list[Path]:
    candidates = []
    for file in dist.files or ():
        name = Path(str(file)).name.lower()
        if re.match(r"^(license|licence|copying|notice)([.\-_].*)?$", name):
            location = Path(dist.locate_file(file))
            if location.is_file() and not location.is_symlink():
                candidates.append(location)
    return sorted(set(candidates))


def safe_component_name(name: str, version: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{name}-{version}")


def python_notices(destination: Path) -> list[str]:
    lines = ["## Frozen Python service", ""]
    for dist in python_distributions():
        name = dist.metadata["Name"]
        version = dist.version
        license_files = license_files_for_distribution(dist)
        if not license_files:
            raise ValueError(f"No license text found for Python distribution {name} {version}")
        component = safe_component_name(name, version)
        target = destination / component
        target.mkdir(parents=True, exist_ok=False)
        for index, source in enumerate(license_files, start=1):
            shutil.copyfile(source, target / f"{index:02d}-{source.name}")
        expression = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see bundled text"
        lines.append(f"- {name} {version} — {expression}; license text: `third_party_licenses/{component}/`")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError(f"Python runtime license not found: {python_license}")
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    shutil.copyfile(python_license, destination / f"Python-{version}-LICENSE.txt")
    lines.append(f"- CPython {version} — PSF License; text: `third_party_licenses/Python-{version}-LICENSE.txt`")
    lines.append("")
    return lines


def node_package_dir(node_modules: Path, name: str) -> Path:
    return node_modules.joinpath(*name.split("/"))


def frontend_notices(project: Path, destination: Path) -> list[str]:
    import json

    lock = json.loads((project / "web" / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    root = packages[""]
    pending = deque(root.get("dependencies", {}))
    visited: set[str] = set()
    lines = ["## Browser workbench", ""]
    while pending:
        name = pending.popleft()
        if name in visited:
            continue
        visited.add(name)
        entry = packages.get(f"node_modules/{name}")
        if entry is None:
            raise ValueError(f"Runtime npm package missing from lockfile: {name}")
        pending.extend(entry.get("dependencies", {}))
        package_dir = node_package_dir(project / "web" / "node_modules", name)
        license_files = sorted(
            path for path in package_dir.iterdir()
            if path.is_file() and re.match(r"^(license|licence|copying|notice)([.\-_].*)?$", path.name.lower())
        ) if package_dir.is_dir() else []
        if not license_files:
            raise ValueError(f"No license text found for npm package {name} {entry['version']}")
        component = safe_component_name(name, entry["version"])
        target = destination / component
        target.mkdir(parents=True, exist_ok=False)
        for index, source in enumerate(license_files, start=1):
            shutil.copyfile(source, target / f"{index:02d}-{source.name}")
        lines.append(
            f"- {name} {entry['version']} — {entry.get('license', 'see bundled text')}; "
            f"license text: `third_party_licenses/{component}/`"
        )
    lines.append("")
    return lines


def build(project: Path, plugin: Path) -> tuple[int, int]:
    if not (plugin / "plugin.json").is_file() or not (project / "web" / "package-lock.json").is_file():
        raise ValueError("Expected source project and built plugin paths")
    license_dir = plugin / "third_party_licenses"
    notice_file = plugin / "THIRD_PARTY_NOTICES.md"
    if license_dir.exists() or notice_file.exists():
        raise ValueError("License output already exists; use a fresh package directory")
    license_dir.mkdir()
    python_lines = python_notices(license_dir)
    frontend_lines = frontend_notices(project, license_dir)
    notice_file.write_text(
        "# Third-party notices\n\n"
        "This conservative inventory covers the Windows service build/runtime dependency graph "
        "and production browser dependency graph; some build tools and TypeScript types are not "
        "present in the final executable or JavaScript bundle. Their own licenses apply to their "
        "code. The inventory is generated from the build environment and npm lockfile.\n\n"
        + "\n".join(python_lines + frontend_lines),
        encoding="utf-8",
    )
    return len(python_lines) - 3, len(frontend_lines) - 3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    python_count, node_count = build(args.project.resolve(), args.plugin.resolve())
    print(f"Bundled {python_count} Python and {node_count} browser dependency notices")


if __name__ == "__main__":
    main()
