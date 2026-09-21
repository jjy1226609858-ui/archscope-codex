#!/usr/bin/env python3
"""Open a workbench through the packaged MCP tool and stop only that new service."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def result(response) -> dict:
    if response.isError:
        raise AssertionError(response.content)
    if response.structuredContent:
        return response.structuredContent.get("result", response.structuredContent)
    return json.loads(response.content[0].text)


async def exercise(plugin: Path, data: Path, *, existing: bool) -> None:
    if data.exists() and not existing:
        raise AssertionError(f"Refusing existing smoke data: {data}")
    if not data.exists() and existing:
        raise AssertionError(f"Expected existing smoke data: {data}")
    data.mkdir(parents=True, exist_ok=True)
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
            first = result(await session.call_tool("archscope_open_workbench", {"project_id": "mini_planner"}))
            assert first["status"] == "ok", first
            state = first["data"]
            assert state["service_status"] == "started", state
            pid = int(state["pid"])
            url = state["url"].rstrip("/")
            with urllib.request.urlopen(f"{url}/api/health", timeout=5) as stream:
                health = json.loads(stream.read())
            assert health["status"] == "ok", health
            with urllib.request.urlopen(url, timeout=5) as stream:
                html = stream.read().decode("utf-8")
            assert '<div id="root"></div>' in html
            with urllib.request.urlopen(f"{url}/api/session", timeout=5) as stream:
                assert json.loads(stream.read())["token"]
            for headers, expected_status in (
                ({"Host": "testserver"}, 400),
                ({"Origin": "https://attacker.example"}, 403),
                ({"Sec-Fetch-Site": "cross-site"}, 403),
            ):
                request = urllib.request.Request(f"{url}/api/session", headers=headers)
                try:
                    urllib.request.urlopen(request, timeout=5)
                except urllib.error.HTTPError as error:
                    assert error.code == expected_status, (headers, error.code)
                    assert b'"token"' not in error.read()
                else:
                    raise AssertionError(f"Unexpected session access: {headers}")
            second = result(await session.call_tool("archscope_open_workbench", {"project_id": "mini_planner"}))
            assert second["data"]["service_status"] == "reused", second
            assert second["data"]["pid"] == pid, second
            print(json.dumps({"status": "PASS", "pid": pid, "first": "started", "second": "reused", "version": health["data"]["tool_version"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--existing", action="store_true", help="Reuse test data after the previous MCP session has ended")
    args = parser.parse_args()
    asyncio.run(exercise(args.plugin_root.resolve(), args.data_root.resolve(), existing=args.existing))


if __name__ == "__main__":
    main()
