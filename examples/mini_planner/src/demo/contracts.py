from __future__ import annotations

from dataclasses import dataclass


Coordinate = tuple[int, int]


@dataclass(frozen=True)
class Scene:
    width: int
    height: int
    blocked: frozenset[Coordinate]

    def contains(self, point: Coordinate) -> bool:
        x, y = point
        return 0 <= x < self.width and 0 <= y < self.height

    def summary(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height, "blocked_cells": len(self.blocked)}


@dataclass(frozen=True)
class PlanningRequest:
    start: Coordinate
    goal: Coordinate

    def summary(self) -> dict[str, list[int]]:
        return {"start": list(self.start), "goal": list(self.goal)}


@dataclass(frozen=True)
class PathResult:
    found: bool
    points: tuple[Coordinate, ...]
    reason: str | None = None

    def summary(self) -> dict[str, object]:
        return {"found": self.found, "point_count": len(self.points), "reason": self.reason}


@dataclass(frozen=True)
class CollisionQuery:
    point: Coordinate

    def summary(self) -> dict[str, list[int]]:
        return {"point": list(self.point)}


@dataclass(frozen=True)
class CollisionDecision:
    traversable: bool

    def summary(self) -> dict[str, bool]:
        return {"traversable": self.traversable}


@dataclass(frozen=True)
class ReportArtifact:
    message: str
    found: bool
    point_count: int

    def summary(self) -> dict[str, object]:
        return {"message": self.message, "found": self.found, "point_count": self.point_count}
