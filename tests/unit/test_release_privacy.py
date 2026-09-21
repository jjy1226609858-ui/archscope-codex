from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tools.audit_release_privacy import is_link_or_junction as release_link, require_inside_release, scan_tree
from tools.build_public_source import is_link_or_junction as source_link


def test_scan_accepts_clean_release(tmp_path: Path) -> None:
    (tmp_path / "plugin.json").write_text('{"name":"archscope"}', encoding="utf-8")
    assert scan_tree(tmp_path, ["test-private-marker"])[0] == 1


@pytest.mark.parametrize("payload", [
    b"test-private-marker",
    "test-private-marker".encode("utf-16-le"),
    b"-----BEGIN " + b"PRIVATE KEY-----",
])
def test_scan_rejects_private_content(tmp_path: Path, payload: bytes) -> None:
    (tmp_path / "payload.bin").write_bytes(payload)
    with pytest.raises(ValueError):
        scan_tree(tmp_path, ["test-private-marker"])


def test_scan_rejects_generated_cache(tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"test")
    with pytest.raises(ValueError, match="Local state"):
        scan_tree(tmp_path, [])


def test_scan_rejects_resolved_path_outside_release(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    with pytest.raises(ValueError, match="escapes release directory"):
        require_inside_release(release, release / ".." / "private.txt")


def test_release_gates_reject_windows_reparse_attribute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = 0x400
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", marker, raising=False)
    monkeypatch.setattr(Path, "lstat", lambda _path: SimpleNamespace(st_file_attributes=marker))
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    assert source_link(tmp_path)
    assert release_link(tmp_path)
