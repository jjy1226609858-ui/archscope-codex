from __future__ import annotations

from collections import deque
from collections.abc import Callable

from demo.collision.api import check
from demo.contracts import CollisionDecision, CollisionQuery, PathResult, PlanningRequest, Scene


ProbeObserver = Callable[[CollisionQuery, CollisionDecision], None]


def plan(
    scene: Scene,
    request: PlanningRequest,
    *,
    observe_probe: ProbeObserver | None = None,
    inject_error: bool = False,
) -> PathResult:
    if inject_error:
        raise RuntimeError("Demonstration search failure")
    queue = deque([request.start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {request.start: None}
    while queue:
        current = queue.popleft()
        if current == request.goal:
            points: list[tuple[int, int]] = []
            cursor: tuple[int, int] | None = current
            while cursor is not None:
                points.append(cursor)
                cursor = previous[cursor]
            points.reverse()
            return PathResult(found=True, points=tuple(points))
        x, y = current
        for point in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if point in previous:
                continue
            query = CollisionQuery(point)
            decision = check(scene, query)
            if observe_probe:
                observe_probe(query, decision)
            if decision.traversable:
                previous[point] = current
                queue.append(point)
    return PathResult(found=False, points=(), reason="NO_PATH")
