from __future__ import annotations

from pathlib import Path

import pytest

from archscope.model import ArchitectureError, load_architecture


ROOT = Path(__file__).resolve().parents[2]


def test_example_architecture_is_deterministic() -> None:
    path = ROOT / "examples" / "mini_planner" / "system.arch"
    first = load_architecture(path)
    second = load_architecture(path)
    assert first.digest == second.digest
    assert first.model["project"]["id"] == "mini_planner"
    assert first.modules_by_id["planning"]["kind"] == "composite"


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "duplicate.arch"
    invalid.write_text("archspec: '0.1'\narchspec: '0.1'\n", encoding="utf-8")
    with pytest.raises(ArchitectureError) as error:
        load_architecture(invalid)
    assert error.value.diagnostics[0]["diagnostic_id"] == "ARCH_PARSE_ERROR"
    assert "duplicate key" in error.value.diagnostics[0]["message"]


def test_yaml_alias_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "alias.arch"
    invalid.write_text("archspec: &version '0.1'\ncopy: *version\n", encoding="utf-8")
    with pytest.raises(ArchitectureError) as error:
        load_architecture(invalid)
    assert error.value.diagnostics[0]["diagnostic_id"] == "ARCH_PARSE_ERROR"


def test_unknown_flow_port_has_semantic_diagnostic(tmp_path: Path) -> None:
    source = (ROOT / "examples" / "mini_planner" / "system.arch").read_text(encoding="utf-8")
    invalid = tmp_path / "dangling.arch"
    invalid.write_text(
        source.replace(
            "to:\n    module: reporter\n    port: path\n  transport",
            "to:\n    module: reporter\n    port: missing\n  transport",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArchitectureError) as error:
        load_architecture(invalid)
    missing = next(item for item in error.value.diagnostics if item["diagnostic_id"] == "FLOW_ENDPOINT_MISSING")
    assert "missing port" in missing["message"].lower()
