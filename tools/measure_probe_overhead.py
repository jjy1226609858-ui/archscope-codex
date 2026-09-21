#!/usr/bin/env python3
"""Measure the demo probe cost without claiming a machine-independent bound."""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

from archscope.telemetry import NullEventWriter, RuntimeEventWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "mini_planner" / "src"))
from demo.main import execute


def main() -> None:
    scenario = ROOT / "examples" / "mini_planner" / "scenarios" / "normal.json"
    durations: dict[str, list[float]] = {"off": [], "on": []}
    event_count = 0
    expected = None
    with tempfile.TemporaryDirectory(prefix="archscope-probe-") as directory:
        for trial in range(8):
            for mode in ("off", "on") if trial % 2 == 0 else ("on", "off"):
                event_path = Path(directory) / f"{mode}-{trial}.jsonl"
                writer = NullEventWriter() if mode == "off" else RuntimeEventWriter(
                    event_path, project_id="mini_planner", run_id=f"measure-{trial}", arch_revision="measurement", code_revision="measurement",
                )
                started = time.perf_counter()
                result = execute(scenario, writer)
                elapsed_ms = (time.perf_counter() - started) * 1000
                writer.close()
                if expected is None:
                    expected = result
                elif result != expected:
                    raise AssertionError("业务返回值在开启/关闭观测时不同")
                if mode == "on":
                    event_count = len(event_path.read_text(encoding="utf-8").splitlines())
                if trial > 0:  # discard one warm-up sample for each mode
                    durations[mode].append(elapsed_ms)
    off = statistics.median(durations["off"])
    on = statistics.median(durations["on"])
    print(json.dumps({
        "status": "PASS", "scenario": "normal.json", "samples_per_mode": len(durations["on"]),
        "event_count_when_on": event_count, "event_count_when_off": 0,
        "median_ms_off": round(off, 3), "median_ms_on": round(on, 3),
        "median_extra_ms": round(on - off, 3), "median_ratio": round(on / off, 3) if off else None,
        "note": "This measurement is specific to this machine and workload; it is not a performance guarantee.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
