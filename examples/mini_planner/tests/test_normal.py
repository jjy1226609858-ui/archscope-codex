from demo.data.api import load_scene
from demo.reporter.api import render
from demo.search.api import plan


def test_normal_path(project_root):
    scene, request, _ = load_scene(project_root / "scenarios" / "normal.json")
    result = plan(scene, request)
    assert result.found
    assert result.points[0] == request.start
    assert result.points[-1] == request.goal
    assert render(result).point_count == len(result.points)
