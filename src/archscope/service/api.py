from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from archscope import __version__
from archscope.paths import web_dist_path
from archscope.service.application import ArchScopeApplication


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunRequest(StrictRequest):
    project_id: str
    profile_id: str
    expected_architecture_digest: str
    idempotency_key: str = Field(min_length=1, max_length=120)


class CheckRequest(StrictRequest):
    project_id: str
    expected_architecture_digest: str
    expected_code_digest: str
    strict: bool = True


class ProposalRequest(StrictRequest):
    project_id: str
    candidate_text: str = Field(min_length=1, max_length=524288)
    expected_architecture_digest: str
    rationale: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=120)


class VisualProposalRequest(StrictRequest):
    project_id: str
    modules: list[dict] = Field(max_length=500)
    flows: list[dict] = Field(max_length=2000)
    expected_architecture_digest: str
    rationale: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=120)


class ReviewRequest(StrictRequest):
    project_id: str
    expected_base_digest: str
    expected_candidate_digest: str
    acknowledgement: str


class TaskPrepareRequest(StrictRequest):
    project_id: str
    module_id: str
    objective: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    expected_architecture_digest: str
    expected_code_digest: str
    idempotency_key: str = Field(min_length=1, max_length=120)


class TaskScopeReviewRequest(StrictRequest):
    project_id: str
    expected_version: int = Field(ge=1)
    acknowledgement: str


class TaskUpdateRequest(StrictRequest):
    project_id: str
    action: str
    expected_version: int = Field(ge=1)
    actor_id: str = Field(min_length=1, max_length=120)
    lease_seconds: int = Field(default=900, ge=60, le=3600)
    declaration: str | None = Field(default=None, max_length=2000)
    expected_snapshot_digest: str | None = None


def _same_origin(request: Request, origin: str) -> bool:
    try:
        supplied = urlsplit(origin)
        actual = urlsplit(str(request.base_url))
        return (
            supplied.scheme == actual.scheme
            and supplied.hostname == actual.hostname
            and supplied.port == actual.port
            and not supplied.username and not supplied.password
            and not supplied.path and not supplied.query and not supplied.fragment
        )
    except ValueError:
        return False


def _http_rejection(diagnostic_id: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": {"status": "error", "diagnostics": [{"diagnostic_id": diagnostic_id, "status": "FAIL", "message": message}]}},
    )


def create_app(
    application: ArchScopeApplication,
    *,
    default_project_id: str,
    static_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="ArchScope Workbench", version=__version__)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    session_token = secrets.token_urlsafe(32)
    web_root = Path(static_path or web_dist_path()).resolve()

    @app.middleware("http")
    async def protect_local_writes(request: Request, call_next):
        session_read = request.url.path == "/api/session" and request.method in {"GET", "HEAD"}
        if request.method not in {"GET", "HEAD", "OPTIONS"} or session_read:
            origin = request.headers.get("origin")
            if (origin is not None and not _same_origin(request, origin)) or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                response = _http_rejection("HTTP_ORIGIN_REJECTED", "Cross-origin workbench requests are not allowed.")
            elif not session_read and not hmac.compare_digest(request.headers.get("x-archscope-session", ""), session_token):
                response = _http_rejection("HTTP_SESSION_REQUIRED", "This workbench session is missing or expired. Reload the page and retry.")
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/session")
    def browser_session() -> dict:
        return {"status": "ok", "token": session_token}

    @app.get("/api/health")
    def health() -> dict:
        return application.health(default_project_id)

    @app.get("/api/project")
    def get_project(project_id: str = Query(default_project_id), revision: str | None = None) -> dict:
        result = application.get_project(project_id, revision)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/api/runtime-setup")
    def runtime_setup(project_id: str = Query(default_project_id)) -> dict:
        result = application.runtime_setup(project_id)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/api/graph")
    def get_graph(project_id: str = Query(default_project_id), revision: str | None = None, run_id: str | None = None) -> dict:
        result = application.graph(project_id, revision, run_id)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/api/modules/{module_id}")
    def get_module(module_id: str, project_id: str = Query(default_project_id), revision: str | None = None, run_id: str | None = None) -> dict:
        result = application.get_module(project_id, module_id, revision, run_id)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/api/runs")
    def run_profile(request: RunRequest) -> dict:
        result = application.run_profile(
            request.project_id,
            request.profile_id,
            request.expected_architecture_digest,
            request.idempotency_key,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.post("/api/checks")
    def run_check(request: CheckRequest) -> dict:
        result = application.check(
            request.project_id,
            request.expected_architecture_digest,
            request.expected_code_digest,
            request.strict,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.post("/api/proposals")
    def create_proposal(request: ProposalRequest) -> dict:
        result = application.propose_architecture(
            request.project_id,
            request.candidate_text,
            request.expected_architecture_digest,
            request.rationale,
            request.idempotency_key,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.get("/api/architecture-editor")
    def get_architecture_editor(project_id: str = Query(default_project_id)) -> dict:
        result = application.get_architecture_editor(project_id)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/api/visual-proposals")
    def create_visual_proposal(request: VisualProposalRequest) -> dict:
        result = application.propose_visual_edit(
            request.project_id, request.modules, request.flows,
            request.expected_architecture_digest, request.rationale, request.idempotency_key,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.get("/api/proposals")
    def list_proposals(project_id: str = Query(default_project_id), state: str | None = None) -> dict:
        result = application.list_proposals(project_id, state)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/api/review/{proposal_id}")
    def review_proposal(proposal_id: str, request: ReviewRequest) -> dict:
        result = application.review_proposal(
            request.project_id,
            proposal_id,
            request.expected_base_digest,
            request.expected_candidate_digest,
            request.acknowledgement,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.post("/api/tasks")
    def prepare_task(request: TaskPrepareRequest) -> dict:
        result = application.prepare_task(
            request.project_id,
            request.module_id,
            request.objective,
            request.evidence_refs,
            request.expected_architecture_digest,
            request.expected_code_digest,
            request.idempotency_key,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.get("/api/tasks")
    def list_tasks(project_id: str = Query(default_project_id), state: str | None = None) -> dict:
        result = application.get_task(project_id, state=state)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str, project_id: str = Query(default_project_id)) -> dict:
        result = application.get_task(project_id, task_id)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/api/tasks/{task_id}/resume")
    def resume_task(task_id: str, project_id: str = Query(default_project_id)) -> dict:
        result = application.resume_task(project_id, task_id)
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.post("/api/tasks/{task_id}/approve-scope")
    def approve_task_scope(task_id: str, request: TaskScopeReviewRequest) -> dict:
        result = application.approve_task_scope(request.project_id, task_id, request.expected_version, request.acknowledgement)
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.post("/api/tasks/{task_id}/update")
    def update_task(task_id: str, request: TaskUpdateRequest) -> dict:
        result = application.update_task(
            request.project_id,
            task_id,
            request.action,
            request.expected_version,
            request.actor_id,
            request.lease_seconds,
            request.declaration,
            request.expected_snapshot_digest,
        )
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    @app.get("/api/evidence")
    def read_evidence(evidence_ref: str, project_id: str = Query(default_project_id)) -> dict:
        result = application.read_evidence(project_id, evidence_ref)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/api/operations/{operation_id}")
    def get_operation(operation_id: str, project_id: str = Query(default_project_id), cursor: int = 0, limit: int = 100) -> dict:
        result = application.get_operation(project_id, operation_id, cursor, limit)
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.post("/api/operations/{operation_id}/cancel")
    def cancel_operation(operation_id: str, project_id: str = Query(default_project_id)) -> dict:
        result = application.cancel_run(project_id, operation_id)
        if result["status"] == "error":
            raise HTTPException(status_code=409, detail=result)
        return result

    if web_root.is_dir() and (web_root / "index.html").is_file():
        assets = web_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(web_root / "index.html")
    else:
        @app.get("/")
        def missing_frontend() -> dict:
            return {
                "status": "not_ready",
                "message": "Web assets are not built. Run the documented web build first.",
                "api": "/api/graph",
            }

    return app
