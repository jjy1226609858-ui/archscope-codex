from __future__ import annotations

from demo.contracts import PathResult, ReportArtifact


def render(result: PathResult) -> ReportArtifact:
    message = f"Path found with {len(result.points)} points" if result.found else f"No path found: {result.reason}"
    return ReportArtifact(message=message, found=result.found, point_count=len(result.points))
