from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from archscope.telemetry import NullEventWriter, RuntimeEventWriter
from demo.data.api import load_scene
from demo.reporter.api import render
from demo.search.api import plan


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def execute(scenario: str | Path, writer: RuntimeEventWriter | NullEventWriter) -> dict[str, Any]:
    writer.emit("run.started", payload={"scenario": Path(scenario).name})
    writer.emit("module.started", module_id="app")
    try:
        writer.emit("module.started", module_id="data")
        try:
            scene, request, options = load_scene(scenario)
        except Exception as exc:
            writer.emit("module.failed", module_id="data", payload={"error_type": type(exc).__name__, "message": str(exc)})
            raise
        writer.emit("port.observed", module_id="data", payload={"direction": "out", "port_id": "scene", "summary": scene.summary()})
        writer.emit("port.observed", module_id="data", payload={"direction": "out", "port_id": "request", "summary": request.summary()})
        writer.emit("module.finished", module_id="data")
        writer.emit("flow.transferred", flow_id="F_SCENE", payload={"summary": scene.summary()})
        writer.emit("flow.transferred", flow_id="F_REQUEST", payload={"summary": request.summary()})

        pause = options.get("pause_seconds", 0)
        if isinstance(pause, (int, float)) and 0 < pause <= 30:
            time.sleep(pause)

        writer.emit("module.started", module_id="search")
        collision_active = False
        probe_count = 0

        def observe_probe(query: Any, decision: Any) -> None:
            nonlocal collision_active, probe_count
            if not collision_active:
                writer.emit("module.started", module_id="collision")
                collision_active = True
            probe_count += 1
            writer.emit("flow.transferred", flow_id="F_PROBE", payload={"summary": query.summary()})
            writer.emit("flow.transferred", flow_id="F_VERDICT", payload={"summary": decision.summary()})

        try:
            path_result = plan(
                scene,
                request,
                observe_probe=observe_probe if writer.enabled else None,
                inject_error=options.get("inject_search_error") is True,
            )
        except Exception as exc:
            writer.emit("module.failed", module_id="search", payload={"error_type": type(exc).__name__, "message": str(exc)})
            raise
        finally:
            if collision_active:
                writer.emit("module.finished", module_id="collision", payload={"probe_count": probe_count})
        writer.emit("port.observed", module_id="search", payload={"direction": "out", "port_id": "path", "summary": path_result.summary()})
        writer.emit("module.finished", module_id="search", payload={"probe_count": probe_count})
        writer.emit("flow.transferred", flow_id="F_PATH", payload={"summary": path_result.summary()})

        writer.emit("module.started", module_id="reporter")
        report = render(path_result)
        writer.emit("port.observed", module_id="reporter", payload={"direction": "out", "port_id": "report", "summary": report.summary()})
        writer.emit("module.finished", module_id="reporter")
        writer.emit("module.finished", module_id="app")
        writer.emit("run.finished", payload={"status": "succeeded", "report": report.summary()})
        return {"status": "succeeded", "report": report.summary()}
    except Exception as exc:
        writer.emit("module.failed", module_id="app", payload={"error_type": type(exc).__name__, "message": str(exc)})
        writer.emit("run.finished", payload={"status": "failed", "error_type": type(exc).__name__, "message": str(exc)})
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arch-revision", required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--disable-observation", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    writer = NullEventWriter() if args.disable_observation else RuntimeEventWriter(
        args.events,
        project_id=args.project_id,
        run_id=args.run_id,
        arch_revision=args.arch_revision,
        code_revision=args.code_revision,
    )
    started = time.perf_counter()
    try:
        result = execute(args.scenario, writer)
    except Exception as exc:
        _write_result(Path(args.result), {"status": "failed", "error_type": type(exc).__name__, "message": str(exc), "target_duration_ms": round((time.perf_counter() - started) * 1000, 3)})
        raise SystemExit(1)
    finally:
        writer.close()
    result["target_duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    _write_result(Path(args.result), result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
