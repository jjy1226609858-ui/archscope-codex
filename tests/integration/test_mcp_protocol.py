from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[2]


async def _exercise_plugin_launcher() -> None:
    params = StdioServerParameters(
        command="powershell.exe",
        args=[
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "plugin" / "scripts" / "start_mcp.ps1"),
        ],
        cwd=str(ROOT.parent),
        env={**os.environ, "ARCHSCOPE_PYTHON": sys.executable},
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tool_list = await session.list_tools()
            names = {tool.name for tool in tool_list.tools}
            assert names == {
                "archscope_health",
                "archscope_get_project",
                "archscope_get_module",
                "archscope_open_workbench",
                "archscope_run_profile",
                "archscope_get_operation",
                "archscope_cancel_run",
                "archscope_check",
                "archscope_propose_arch",
                "archscope_prepare_task",
                "archscope_get_task",
                "archscope_resume_task",
                "archscope_update_task",
                "archscope_read_evidence",
            }
            response = await session.call_tool("archscope_get_project", {"project_id": "mini_planner"})
            assert not response.isError
            if response.structuredContent:
                payload = response.structuredContent["result"] if "result" in response.structuredContent else response.structuredContent
            else:
                payload = json.loads(response.content[0].text)
            assert payload["status"] == "ok"
            assert payload["data"]["project"]["id"] == "mini_planner"
            task_response = await session.call_tool("archscope_get_task", {"project_id": "mini_planner"})
            assert not task_response.isError


def test_stdio_plugin_launcher_and_tools() -> None:
    asyncio.run(_exercise_plugin_launcher())
