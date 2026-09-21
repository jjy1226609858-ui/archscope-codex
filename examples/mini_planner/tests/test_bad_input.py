import pytest

from demo.data.api import load_scene


def test_bad_input_stops_at_data_boundary(project_root):
    with pytest.raises(ValueError, match="start is outside the grid bounds"):
        load_scene(project_root / "scenarios" / "bad_input.json")
