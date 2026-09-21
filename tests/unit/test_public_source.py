import os
from pathlib import Path
import subprocess
import zipfile

import pytest
import yaml

from tools.audit_release_privacy import scan_tree
from tools.build_public_source import DIRECTORIES, FILES, audit_file, build, require_inside, selected_files


ROOT = Path(__file__).resolve().parents[2]


def prepared_root(tmp_path: Path) -> Path:
    for name in FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("safe source\n", encoding="utf-8")
    for name in DIRECTORIES:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "public.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "private.pyc").write_bytes(b"local-user")
    (tmp_path / "examples" / "mini_planner" / ".archscope").mkdir(parents=True)
    (tmp_path / "examples" / "mini_planner" / ".archscope" / "run.json").write_text("private")
    return tmp_path


def test_public_archive_is_allowlisted_and_omits_runtime_data(tmp_path: Path) -> None:
    root = prepared_root(tmp_path / "source")
    output = tmp_path / "release.zip"
    count = build(root, output, "local-user")
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert count == len(FILES) + 1
        assert "ArchScope/src/public.py" in names
        assert "ArchScope/RELEASE_CONTENTS.sha256" in names
        assert not any("__pycache__" in name or ".archscope" in name for name in names)


@pytest.mark.parametrize("content", [
    b"path = " + b"C:" + b"\\Users\\someone\\secret.txt",
    b"path = " + b"/home" + b"/someone/secret.txt",
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"local-user",
])
def test_public_archive_rejects_private_content(tmp_path: Path, content: bytes) -> None:
    root = prepared_root(tmp_path / "source")
    (root / "src" / "public.py").write_bytes(content)
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError):
        build(root, output, "local-user")
    assert not output.exists()


def test_binary_source_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "secret.bin"
    path.write_bytes(b"hidden\x00data")
    with pytest.raises(ValueError, match="Binary"):
        audit_file(tmp_path, path, None)


def test_public_source_rejects_resolved_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "private.py"
    outside.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes source root"):
        require_inside(root, root / ".." / outside.name)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_release_gates_reject_windows_directory_junction(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "personal.txt").write_text("private", encoding="utf-8")
    source = prepared_root(tmp_path / "source")
    junction = source / "src" / "linked-private"
    result = subprocess.run(
        ["cmd", "/c", f'mklink /J "{junction}" "{private}"'],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        pytest.skip("Windows junction creation unavailable")
    with pytest.raises(ValueError, match="escapes source root"):
        selected_files(source)

    release = tmp_path / "release"
    release.mkdir()
    release_junction = release / "linked-private"
    result = subprocess.run(
        ["cmd", "/c", f'mklink /J "{release_junction}" "{private}"'],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        pytest.skip("Windows release junction creation unavailable")
    with pytest.raises(ValueError, match="escapes release directory"):
        scan_tree(release, [])


def test_public_windows_ci_is_unprivileged_and_allowlisted() -> None:
    assert ".github/workflows/windows-ci.yml" in FILES
    workflow = yaml.load((ROOT / ".github/workflows/windows-ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["test-and-package"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
    assert upload["with"]["path"] == "${{ runner.temp }}/ArchScope-windows-candidate/"
    assert upload["with"]["include-hidden-files"] == "true"
    assert upload["with"]["if-no-files-found"] == "error"
