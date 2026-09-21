from __future__ import annotations

from demo.contracts import CollisionDecision, CollisionQuery, Scene


def check(scene: Scene, query: CollisionQuery) -> CollisionDecision:
    return CollisionDecision(traversable=scene.contains(query.point) and query.point not in scene.blocked)
