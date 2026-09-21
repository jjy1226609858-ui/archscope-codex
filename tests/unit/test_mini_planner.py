from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SRC = ROOT / "examples" / "mini_planner" / "src"
if str(EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_SRC))

from demo.data.api import load_scene
from demo.reporter.api import render
from demo.search.api import plan


def scenario(name: str) -> Path:
    return ROOT / "examples" / "mini_planner" / "scenarios" / name


def test_normal_planner_uses_ordinary_python_calls() -> None:
    scene, request, _ = load_scene(scenario("normal.json"))
    result = plan(scene, request)
    report = render(result)
    assert result.found is True
    assert result.points[0] == request.start
    assert result.points[-1] == request.goal
    assert report.point_count == len(result.points)


def test_bad_input_fails_at_data_boundary() -> None:
    with pytest.raises(ValueError, match="start is outside the grid bounds"):
        load_scene(scenario("bad_input.json"))


def test_injected_search_error_is_not_misreported_as_no_path() -> None:
    scene, request, _ = load_scene(scenario("search_error.json"))
    with pytest.raises(RuntimeError, match="Demonstration search failure"):
        plan(scene, request, inject_error=True)
