from demo.data.api import load_scene
from demo.search.api import plan


def test_probe_observer_does_not_change_result(project_root):
    scene, request, _ = load_scene(project_root / "scenarios" / "normal.json")
    observed = []
    with_observer = plan(scene, request, observe_probe=lambda query, decision: observed.append((query, decision)))
    without_observer = plan(scene, request)
    assert observed
    assert with_observer == without_observer
