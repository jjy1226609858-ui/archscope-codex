"""Fail a release artifact if it contains obvious local data or private keys.

This is a release gate, not a guarantee that arbitrary secrets are absent.
Review the archive contents and diff before publishing.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat


FORBIDDEN_PARTS = {".archscope", ".git", ".pytest_cache", ".venv", "__pycache__", "node_modules"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db"}
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN " + b"RSA PRIVATE KEY-----",
    b"-----BEGIN " + b"EC PRIVATE KEY-----",
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
)


def require_inside_release(root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Release path escapes release directory: {path.relative_to(root)}")


def is_link_or_junction(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def scan_tree(root: Path, deny: list[str]) -> tuple[int, int]:
    if not root.is_dir() or is_link_or_junction(root):
        raise ValueError(f"Release directory does not exist or is linked: {root}")
    username = os.environ.get("USERNAME") or Path.home().name
    markers = {username, str(Path.home()), str(Path.home()).replace("\\", "/"), *deny}
    encoded = {
        marker.encode(encoding)
        for marker in markers if marker
        for encoding in ("utf-8", "utf-16-le")
    }
    count = total = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        require_inside_release(root, path)
        if is_link_or_junction(path):
            raise ValueError(f"Linked release path: {relative}")
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            raise ValueError(f"Local state directory in release: {relative}")
        if not path.is_file():
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.lower().startswith(".env"):
            raise ValueError(f"Local data or credential file in release: {relative}")
        data = path.read_bytes()
        lower = data.lower()
        for marker in encoded:
            if marker.lower() in lower:
                raise ValueError(f"Local identity or path marker in release file: {relative}")
        if any(marker in data for marker in PRIVATE_KEY_MARKERS):
            raise ValueError(f"Private key marker in release file: {relative}")
        count += 1
        total += len(data)
    return count, total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_directory", type=Path)
    parser.add_argument("--deny", action="append", default=[], help="Additional literal private marker")
    args = parser.parse_args()
    count, total = scan_tree(args.release_directory.resolve(), args.deny)
    print(f"PASS privacy marker scan: {count} files, {total} bytes")


if __name__ == "__main__":
    main()
