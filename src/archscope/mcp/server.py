from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.parse import urlencode

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

from archscope.paths import default_registry_path
from archscope.service.application import ArchScopeApplication
from archscope.service.workbench import WorkbenchManager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("archscope.mcp")

mcp = FastMCP("ArchScope")
application = ArchScopeApplication(default_registry_path())
workbench = WorkbenchManager(application)


@mcp.tool()
def archscope_health(project_id: str | None = None) -> dict:
    """Return ArchScope version, implemented capabilities, and optional project readiness."""
    return application.health(project_id)


@mcp.tool()
def archscope_get_project(project_id: str, revision: str | None = None) -> dict:
    """Read one registered project's architecture summary without executing target code."""
    return application.get_project(project_id, revision)


@mcp.tool()
def archscope_get_module(project_id: str, module_id: str, revision: str | None = None) -> dict:
    """Read responsibilities, ports, children, bindings and declared flows for one module."""
    return application.get_module(project_id, module_id, revision)


@mcp.tool()
def archscope_run_profile(
    project_id: str,
    profile_id: str,
    expected_architecture_digest: str,
    idempotency_key: str,
) -> dict:
    """Start one predeclared project run profile; arbitrary commands are not accepted."""
    return application.run_profile(project_id, profile_id, expected_architecture_digest, idempotency_key)


@mcp.tool()
def archscope_get_operation(project_id: str, operation_id: str, cursor: int = 0, limit: int = 100) -> dict:
    """Read persisted state and a bounded page of runtime events for one operation."""
    return application.get_operation(project_id, operation_id, cursor, limit)


@mcp.tool()
def archscope_cancel_run(project_id: str, operation_id: str) -> dict:
    """Cancel a running profile started by this ArchScope server process."""
    return application.cancel_run(project_id, operation_id)


@mcp.tool()
def archscope_check(
    project_id: str,
    expected_architecture_digest: str,
    expected_code_digest: str,
    strict: bool = True,
) -> dict:
    """Run the deterministic source-boundary checker against exact architecture and code digests."""
    return application.check(project_id, expected_architecture_digest, expected_code_digest, strict)


@mcp.tool()
def archscope_propose_arch(
    project_id: str,
    candidate_text: str,
    expected_architecture_digest: str,
    rationale: str,
    idempotency_key: str,
) -> dict:
    """Save a validated architecture candidate for human review; this never approves or overwrites the baseline."""
    return application.propose_architecture(
        project_id,
        candidate_text,
        expected_architecture_digest,
        rationale,
        idempotency_key,
    )


@mcp.tool()
def archscope_prepare_task(
    project_id: str,
    module_id: str,
    objective: str,
    evidence_refs: list[str],
    expected_architecture_digest: str,
    expected_code_digest: str,
    idempotency_key: str,
) -> dict:
    """Prepare an evidence-bound repair task for local human scope review; this does not make it claimable."""
    return application.prepare_task(
        project_id,
        module_id,
        objective,
        evidence_refs,
        expected_architecture_digest,
        expected_code_digest,
        idempotency_key,
    )


@mcp.tool()
def archscope_get_task(project_id: str, task_id: str | None = None, state: str | None = None) -> dict:
    """Read one repair task or list project tasks, including scope, lease and independent verification state."""
    return application.get_task(project_id, task_id, state)


@mcp.tool()
def archscope_resume_task(project_id: str, task_id: str) -> dict:
    """Recover a durable task handoff packet, recheck workspace scope and obtain a snapshot token for expired-lease takeover."""
    return application.resume_task(project_id, task_id)


@mcp.tool()
def archscope_update_task(
    project_id: str,
    task_id: str,
    action: str,
    expected_version: int,
    actor_id: str,
    lease_seconds: int = 900,
    declaration: str | None = None,
    expected_snapshot_digest: str | None = None,
) -> dict:
    """Claim, release, declare completion or reverify a blocked task against fresh evidence."""
    return application.update_task(project_id, task_id, action, expected_version, actor_id, lease_seconds, declaration, expected_snapshot_digest)


@mcp.tool()
def archscope_read_evidence(project_id: str, evidence_ref: str) -> dict:
    """Read a typed ArchScope evidence reference without accepting arbitrary filesystem paths."""
    return application.read_evidence(project_id, evidence_ref)


@mcp.tool()
def archscope_open_workbench(project_id: str, module_id: str | None = None, run_id: str | None = None) -> dict:
    """Start or reuse the loopback-only browser workbench for a registered project."""
    try:
        state = workbench.open(project_id)
        query = urlencode({key: value for key, value in {"module": module_id, "run_id": run_id}.items() if value})
        suffix = f"?{query}" if query else ""
        return application._envelope(
            status="ok",
            project_id=project_id,
            architecture_digest=application.architecture_digest(project_id),
            evidence_refs=[f"service:{state['pid']}"],
            data={**state, "url": f"{state['url']}/{suffix}"},
        )
    except Exception as exc:
        logger.exception("Failed to open workbench")
        return application._envelope(
            status="error",
            project_id=project_id,
            diagnostics=[{"diagnostic_id": "WORKBENCH_START_FAILED", "status": "FAIL", "message": str(exc)}],
            data={},
        )


async def _run_stdio() -> None:
    # The SDK's default stdio helper creates a second TextIOWrapper around the
    # process streams.  In a frozen Windows executable that wrapper can close
    # the shared buffer before interpreter shutdown, producing a spurious
    # "I/O operation on closed file" traceback after an otherwise clean MCP
    # session.  Reuse the process text streams so their lifetime remains owned
    # by Python/PyInstaller.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    stdin = anyio.wrap_file(sys.stdin)
    stdout = anyio.wrap_file(sys.stdout)
    async with stdio_server(stdin=stdin, stdout=stdout) as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),
        )


def main() -> None:
    anyio.run(_run_stdio)


if __name__ == "__main__":
    main()
