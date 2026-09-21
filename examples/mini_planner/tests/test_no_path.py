from demo.data.api import load_scene
from demo.search.api import plan


def test_no_path_is_a_domain_result(project_root):
    scene, request, _ = load_scene(project_root / "scenarios" / "no_path.json")
    result = plan(scene, request)
    assert result.found is False
    assert result.reason == "NO_PATH"
