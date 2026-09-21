#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def exercise(command: str, args: list[str]) -> None:
    params = StdioServerParameters(command=command, args=args, env=dict(os.environ))
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            if len(names) != 14 or "archscope_resume_task" not in names:
                raise AssertionError(f"unexpected tools: {names}")
            response = await session.call_tool("archscope_health", {"project_id": "mini_planner"})
            if response.isError:
                raise AssertionError(response.content)
            if response.structuredContent:
                payload = response.structuredContent.get("result", response.structuredContent)
            else:
                payload = json.loads(response.content[0].text)
            if payload["status"] != "ok":
                raise AssertionError(payload)
            print(json.dumps({"status": "PASS", "tool_count": len(names), "tool_version": payload["data"]["tool_version"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    asyncio.run(exercise(parsed.command, parsed.args))


if __name__ == "__main__":
    main()
