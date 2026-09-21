import json
from pathlib import Path

import pytest

from tools.build_third_party_notices import frontend_notices, safe_component_name


def test_component_name_does_not_create_a_nested_path() -> None:
    name = safe_component_name("@xyflow/react", "12.8.6")
    assert name == "-xyflow-react-12.8.6"
    assert "/" not in name and "\\" not in name


def test_frontend_notices_copies_runtime_license(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"dependencies": {"widget": "1.0.0"}},
        "node_modules/widget": {"version": "1.0.0", "license": "MIT"},
    }}), encoding="utf-8")
    widget = web / "node_modules" / "widget"
    widget.mkdir(parents=True)
    (widget / "LICENSE").write_text("MIT sample license", encoding="utf-8")
    destination = tmp_path / "notices"
    destination.mkdir()
    lines = frontend_notices(tmp_path, destination)
    assert len(lines) - 3 == 1
    assert "widget 1.0.0" in "\n".join(lines)
    assert (destination / "widget-1.0.0" / "01-LICENSE").read_text(encoding="utf-8") == "MIT sample license"


def test_frontend_notices_fails_when_license_is_missing(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"dependencies": {"widget": "1.0.0"}},
        "node_modules/widget": {"version": "1.0.0", "license": "MIT"},
    }}), encoding="utf-8")
    (web / "node_modules" / "widget").mkdir(parents=True)
    destination = tmp_path / "notices"
    destination.mkdir()
    with pytest.raises(ValueError, match="No license text"):
        frontend_notices(tmp_path, destination)
