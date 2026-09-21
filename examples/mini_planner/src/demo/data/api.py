from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from demo.contracts import PlanningRequest, Scene


def _coordinate(value: Any, name: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) for item in value):
        raise ValueError(f"{name} must contain two integer coordinates")
    return value[0], value[1]


def load_scene(path: str | Path) -> tuple[Scene, PlanningRequest, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    width, height = payload.get("width"), payload.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")
    blocked = frozenset(_coordinate(item, "blocked") for item in payload.get("blocked", []))
    scene = Scene(width=width, height=height, blocked=blocked)
    request = PlanningRequest(start=_coordinate(payload.get("start"), "start"), goal=_coordinate(payload.get("goal"), "goal"))
    for name, point in (("start", request.start), ("goal", request.goal)):
        if not scene.contains(point):
            raise ValueError(f"{name} is outside the grid bounds")
        if point in scene.blocked:
            raise ValueError(f"{name} is blocked")
    return scene, request, payload
