#!/usr/bin/env python3
"""Check archived revision reads through the installed Windows MCP runtime."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from archscope.service import ArchScopeApplication


def result(response) -> dict:
    if response.isError:
        raise AssertionError(response.content)
    return response.structuredContent.get("result", response.structuredContent) if response.structuredContent else json.loads(response.content[0].text)


async def exercise(plugin: Path, data: Path) -> None:
    registry = data / "projects.json"
    if not registry.is_file():
        raise AssertionError("Run the isolated MCP bootstrap smoke first")
    app = ArchScopeApplication(registry)
    current = app.get_project("mini_planner")
    old_digest = current["architecture_digest"]
    old_name = current["data"]["project"]["name"]
    project = app.registry.get("mini_planner")
    candidate = project.arch_path.read_text(encoding="utf-8").replace(old_name, "打包历史回放验证")
    env = dict(os.environ)
    for key in ("ARCHSCOPE_ROOT", "ARCHSCOPE_REGISTRY", "ARCHSCOPE_PYTHON", "PYTHONPATH"):
        env.pop(key, None)
    env["PLUGIN_DATA"] = str(data)
    params = StdioServerParameters(
        command="powershell.exe",
        args=["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(plugin / "scripts" / "start_mcp.ps1")],
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            proposal = result(await session.call_tool("archscope_propose_arch", {
                "project_id": "mini_planner", "candidate_text": candidate,
                "expected_architecture_digest": old_digest, "rationale": "packaged history smoke",
                "idempotency_key": "packaged-history-smoke",
            }))
            assert proposal["status"] == "ok", proposal
            record = proposal["data"]["proposal"]
            reviewed = app.review_proposal(
                "mini_planner", record["proposal_id"], old_digest, record["candidate_architecture_digest"],
                "我已审阅并批准此架构候选",
            )
            assert reviewed["status"] == "ok", reviewed
            historical = result(await session.call_tool("archscope_get_project", {"project_id": "mini_planner", "revision": old_digest}))
            assert historical["status"] == "ok" and historical["data"]["historical"] is True, historical
            assert historical["data"]["project"]["name"] == old_name, historical
            evidence = result(await session.call_tool("archscope_read_evidence", {
                "project_id": "mini_planner", "evidence_ref": f"arch:{old_digest}",
            }))
            assert evidence["status"] == "ok" and evidence["architecture_digest"] == old_digest, evidence
            current_after = result(await session.call_tool("archscope_get_project", {"project_id": "mini_planner"}))
            assert current_after["architecture_digest"] != old_digest, current_after
            print(json.dumps({"status": "PASS", "old_digest": old_digest, "new_digest": current_after["architecture_digest"], "historical_name": old_name}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("data_root", type=Path)
    arguments = parser.parse_args()
    asyncio.run(exercise(arguments.plugin_root.resolve(), arguments.data_root.resolve()))


if __name__ == "__main__":
    main()
