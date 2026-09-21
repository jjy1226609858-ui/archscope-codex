#!/usr/bin/env python3
"""Verify a packaged MCP session owns a complete real demo run.

This deliberately does not approve architecture or task scope. A one-shot CLI
cannot certify a run after its process exits, so the MCP session stays open
until the target process and event stream have reached a terminal state.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def result(response) -> dict:
    if response.isError:
        raise AssertionError(response.content)
    if response.structuredContent:
        return response.structuredContent.get("result", response.structuredContent)
    return json.loads(response.content[0].text)


async def exercise(plugin: Path, data: Path) -> None:
    if data.exists():
        raise AssertionError(f"Refusing existing smoke data: {data}")
    data.mkdir(parents=True)
    env = dict(os.environ)
    for key in ("ARCHSCOPE_ROOT", "ARCHSCOPE_REGISTRY", "ARCHSCOPE_PYTHON", "PYTHONPATH"):
        env.pop(key, None)
    env["PLUGIN_DATA"] = str(data)
    env["ARCHSCOPE_TARGET_PYTHON"] = str(Path(sys.executable).resolve())
    params = StdioServerParameters(
        command="powershell.exe",
        args=[
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(plugin / "scripts" / "start_mcp.ps1"),
        ],
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            health = result(await session.call_tool("archscope_health", {"project_id": "mini_planner"}))
            assert health["status"] == "ok", health
            project = result(await session.call_tool("archscope_get_project", {"project_id": "mini_planner"}))
            assert project["status"] == "ok", project
            digest = project["architecture_digest"]
            started = result(await session.call_tool("archscope_run_profile", {
                "project_id": "mini_planner",
                "profile_id": "demo-normal",
                "expected_architecture_digest": digest,
                "idempotency_key": f"portable-run-{uuid.uuid4().hex}",
            }))
            assert started["status"] == "ok", started
            operation_id = started["data"]["operation"]["operation_id"]
            for _ in range(120):
                response = result(await session.call_tool("archscope_get_operation", {
                    "project_id": "mini_planner", "operation_id": operation_id,
                    "cursor": 0, "limit": 200,
                }))
                assert response["status"] == "ok", response
                operation = response["data"]["operation"]
                if operation["state"] not in ("pending", "running", "cancelling"):
                    break
                await asyncio.sleep(0.25)
            else:
                raise AssertionError("Packaged demo run did not become terminal within 30 seconds")
            assert operation["state"] == "succeeded", operation
            assert operation["exit_code"] == 0, operation
            assert operation["event_count"] == 131, operation
            assert operation["invalid_event_count"] == 0, operation
            assert operation["loss_marker_count"] == 0, operation
            assert operation.get("observation_coverage") != "incomplete", operation
            assert operation.get("diagnostic_id") is None, operation
            events = operation["events"]
            assert len(events) == 131, len(events)
            assert events[-1]["event_type"] == "run.finished", events[-1]
            print(json.dumps({
                "status": "PASS", "tool_version": health["data"]["tool_version"],
                "operation_id": operation_id, "state": operation["state"],
                "exit_code": operation["exit_code"], "event_count": operation["event_count"],
                "observation_coverage": "complete",
            }))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    asyncio.run(exercise(args.plugin_root.resolve(), args.data_root.resolve()))


if __name__ == "__main__":
    main()
