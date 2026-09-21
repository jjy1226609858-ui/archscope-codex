"""Build a fail-closed, source-only ArchScope archive for public review.

The development checkout is never a release input as a whole. Only the
explicitly listed files and directories below can enter the archive.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ".gitignore",
    ".github/workflows/windows-ci.yml",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "INSTALL.zh-CN.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "RELEASE_NOTES.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-build.txt",
    "tools/build_public_source.py",
    "tools/audit_release_privacy.py",
    "tools/build_third_party_notices.py",
    "tools/build_windows_marketplace.ps1",
    "tools/measure_probe_overhead.py",
    "tools/smoke_mcp.py",
    "tools/smoke_portable_history.py",
    "tools/smoke_portable_run.py",
    "tools/smoke_portable_task.py",
    "tools/smoke_portable_trust.py",
    "tools/smoke_portable_workbench.py",
    "web/index.html",
    "web/package.json",
    "web/package-lock.json",
    "web/tsconfig.app.json",
    "web/tsconfig.json",
    "web/tsconfig.node.json",
    "web/vite.config.ts",
)
DIRECTORIES = ("src", "schemas", "plugin", "examples", "tests", "web/src")
OMIT_DIRS = {
    ".archscope", ".git", ".pytest_cache", ".venv", "__pycache__",
    "build", "dist", "node_modules", "runtime", "resources",
}
OMIT_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}
PATH_RE = re.compile(rb"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/(?:Users|home)/)[^\s\x00\"']{3,}")
SECRET_RE = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")


def require_inside(root: Path, candidate: Path) -> None:
    """Reject links and Windows junctions before copying any release input."""
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Release path escapes source root: {candidate.relative_to(root)}")


def is_link_or_junction(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def selected_files(root: Path) -> list[Path]:
    selected: list[Path] = []
    for name in FILES:
        candidate = root / name
        require_inside(root, candidate)
        if not candidate.is_file() or is_link_or_junction(candidate):
            raise ValueError(f"Required release file missing or linked: {name}")
        selected.append(candidate)
    for name in DIRECTORIES:
        directory = root / name
        require_inside(root, directory)
        if not directory.is_dir() or is_link_or_junction(directory):
            raise ValueError(f"Required release directory missing or linked: {name}")
        for candidate in directory.rglob("*"):
            relative = candidate.relative_to(root)
            require_inside(root, candidate)
            if any(part in OMIT_DIRS for part in relative.parts):
                continue
            if candidate.suffix.lower() in OMIT_SUFFIXES:
                continue
            if candidate.name.lower().startswith(".env"):
                raise ValueError(f"Environment file under release source: {relative}")
            if is_link_or_junction(candidate):
                raise ValueError(f"Linked release path is forbidden: {relative}")
            if candidate.is_file():
                selected.append(candidate)
    return sorted(set(selected), key=lambda item: item.relative_to(root).as_posix())


def audit_file(root: Path, path: Path, username: str | None) -> bytes:
    require_inside(root, path)
    relative = path.relative_to(root).as_posix()
    if is_link_or_junction(path):
        raise ValueError(f"Linked release path is forbidden: {relative}")
    data = path.read_bytes()
    if b"\x00" in data:
        raise ValueError(f"Binary file is not allowed in source archive: {relative}")
    if SECRET_RE.search(data):
        raise ValueError(f"Private key marker found: {relative}")
    match = PATH_RE.search(data)
    if match:
        raise ValueError(f"Absolute machine path found in {relative}: {match.group(0)[:80]!r}")
    if username and username.lower().encode() in data.lower():
        raise ValueError(f"Local username found: {relative}")
    return data


def build(root: Path, output: Path, username: str | None) -> int:
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    selected = selected_files(root)
    contents = [(path.relative_to(root).as_posix(), audit_file(root, path, username)) for path in selected]
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in contents:
            archive.writestr(f"ArchScope/{name}", data)
        checksums = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in contents
        )
        archive.writestr("ArchScope/RELEASE_CONTENTS.sha256", checksums.encode())
    return len(contents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    count = build(args.root.resolve(), args.output.resolve(), os.environ.get("USERNAME") or Path.home().name)
    print(f"Public source archive created with {count} audited files: {args.output}")


if __name__ == "__main__":
    main()
