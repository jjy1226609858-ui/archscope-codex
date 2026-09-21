from __future__ import annotations

import os
import sys
from pathlib import Path


def repository_root() -> Path:
    """Return the source root or a frozen plugin's bundled resources root."""
    configured = os.environ.get("ARCHSCOPE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return (Path(sys.executable).resolve().parent.parent / "resources").resolve()
    return Path(__file__).resolve().parents[2]


def default_registry_path() -> Path:
    configured = os.environ.get("ARCHSCOPE_REGISTRY")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        data_root = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
        if data_root:
            return Path(data_root).expanduser().resolve() / "projects.json"
        local_data = os.environ.get("LOCALAPPDATA")
        if local_data:
            return Path(local_data).expanduser().resolve() / "ArchScope" / "plugin-data" / "projects.json"
        return Path.home().resolve() / ".archscope" / "plugin-data" / "projects.json"
    return repository_root() / "examples" / "projects.json"


def default_schema_path() -> Path:
    configured = os.environ.get("ARCHSCOPE_ARCH_SCHEMA")
    if configured:
        return Path(configured).expanduser().resolve()
    return repository_root() / "schemas" / "arch.schema.json"


def web_dist_path() -> Path:
    configured = os.environ.get("ARCHSCOPE_WEB_DIST")
    if configured:
        return Path(configured).expanduser().resolve()
    return repository_root() / "web" / "dist"


def target_sdk_path() -> Path:
    """Source tree in development; small telemetry SDK copied into a portable plugin."""
    root = repository_root()
    portable = root / "python"
    return portable if (portable / "archscope" / "telemetry").is_dir() else root / "src"
