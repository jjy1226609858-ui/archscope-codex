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


def test_release_privacy_ignores_bare_runner_name_only_in_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    username = "runner" + "admin"
    monkeypatch.setenv("USERNAME", username)
    binary = tmp_path / "extension.pyd"
    binary.write_bytes(b"\x00" + username.encode() + b"\x00")
    assert scan_tree(tmp_path, []) == (1, len(binary.read_bytes()))

    text_file = tmp_path / "notes.txt"
    text_file.write_text(username, encoding="utf-8")
    with pytest.raises(ValueError, match="identity marker"):
        scan_tree(tmp_path, [])


def test_release_privacy_still_rejects_home_path_in_binary(tmp_path: Path) -> None:
    binary = tmp_path / "extension.pyd"
    binary.write_bytes(b"\x00" + str(Path.home()).encode("utf-8") + b"\x00")
    with pytest.raises(ValueError, match="identity or path marker"):
        scan_tree(tmp_path, [])


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


def test_public_windows_ci_gates_release_on_verified_package() -> None:
    assert ".github/workflows/windows-ci.yml" in FILES
    assert "RELEASE_NOTES.md" in FILES
    workflow = yaml.load((ROOT / ".github/workflows/windows-ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    build_job = workflow["jobs"]["test-and-package"]
    assert "permissions" not in build_job
    steps = build_job["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    upload = next(step for step in steps if step.get("name") == "Upload verified Windows package")
    assert upload["if"] == "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
    assert upload["with"]["path"] == "${{ runner.temp }}/ArchScope-windows-candidate/"
    assert upload["with"]["include-hidden-files"] == "true"
    assert upload["with"]["if-no-files-found"] == "error"
    repair = next(step for step in steps if step.get("name", "").startswith("Verify isolated repair regression"))
    assert "tools/smoke_portable_task.py" in repair["run"]
    assert steps.index(repair) < steps.index(upload)
    prepare = next(step for step in steps if step.get("name") == "Prepare audited release files")
    release_upload = next(step for step in steps if step.get("name") == "Upload audited release files")
    assert "github.ref == 'refs/heads/main'" in prepare["if"]
    assert "[release]" in prepare["if"]
    assert steps.index(repair) < steps.index(prepare) < steps.index(release_upload)
    assert ".agents/plugins/marketplace.json" in prepare["run"]
    assert "SHA256SUMS.txt" in prepare["run"]
    assert release_upload["with"]["if-no-files-found"] == "error"

    publish = workflow["jobs"]["publish-release"]
    assert publish["needs"] == "test-and-package"
    assert publish["permissions"] == {"contents": "write"}
    assert "[release]" in publish["if"]
    publish_steps = publish["steps"]
    download = next(step for step in publish_steps if step.get("uses", "").startswith("actions/download-artifact@"))
    assert "release-files" in download["with"]["name"]
    assert any("Get-FileHash" in step.get("run", "") for step in publish_steps)
    create = next(step for step in publish_steps if step.get("name") == "Publish Windows early release")
    assert "gh release create" in create["run"]
    assert "--prerelease" in create["run"]
    assert "git ls-remote --tags" in create["run"]


def test_published_release_smoke_downloads_public_assets_without_credentials() -> None:
    path = ".github/workflows/published-release-smoke.yml"
    assert path in FILES
    workflow = yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["verify-public-download"]
    assert "contents: write" not in str(job)
    assert "jjy1226609858-ui/archscope-codex" in job["if"]
    steps = job["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    resolve = next(step for step in steps if step.get("name") == "Resolve newest published release")
    download = next(step for step in steps if step.get("name") == "Download public assets without credentials")
    verify = next(step for step in steps if step.get("name") == "Verify downloaded hashes and package layout")
    run = next(step for step in steps if step.get("name") == "Audit downloaded source and run downloaded plugin")
    assert "GH_TOKEN" in resolve["env"]
    assert "GH_TOKEN" not in download.get("env", {})
    assert "curl.exe --fail --location" in download["run"]
    assert "Get-FileHash" in verify["run"]
    assert "SHA256SUMS.txt" in verify["run"]
    assert "marketplace.json" in verify["run"]
    assert "audit_release_privacy.py" in run["run"]
    assert run["run"].count("python tools/audit_release_privacy.py") == 1
    assert "python -m pip install -e $source" in run["run"]
    assert "smoke_portable_run.py" in run["run"]
    assert "smoke_portable_task.py" in run["run"]
    assert steps.index(resolve) < steps.index(download) < steps.index(verify) < steps.index(run)
