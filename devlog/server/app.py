"""把 runner 封装成 HTTP 接口的 FastAPI 应用。

这里不写业务逻辑：路由只把 HTTP 请求翻译成 runner 调用，
和 cli/main.py 处理终端输入的方式完全一致。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from devlog.cli import runner
from devlog.core.git_source.scanner import GitSourceError
from devlog.core.llm.deepseek import llm_settings
from devlog.core.llm.base import LLMError
from devlog.core.review.markdown import ReviewExportError
from devlog.core.storage.database import DevLogDB, DatabaseError, default_db_path
from devlog.server import schemas


def create_app(db_path: str | Path | None = None) -> FastAPI:
    """构建配置好的 DevLog API 应用（供 uvicorn 与测试使用）。"""

    resolved_db = (
        str(Path(db_path).expanduser().resolve())
        if db_path is not None
        else str(default_db_path())
    )
    app = FastAPI(
        title="DevLog API",
        description="本地开发复盘工具的 HTTP 接口",
        version="0.1.0",
    )
    app.state.db_path = resolved_db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_db(request: Request):
        db = DevLogDB(request.app.state.db_path)
        try:
            yield db
        finally:
            db.close()

    def project_path(db: DevLogDB, project_id: int) -> str:
        return db.get_project(project_id).path

    @app.get("/api/projects", response_model=list[schemas.ProjectListResponse])
    def list_projects(db=Depends(get_db)):
        return db.list_projects()

    @app.post(
        "/api/projects",
        response_model=schemas.InitResponse,
        status_code=201,
    )
    def create_project(payload: schemas.ProjectCreate, db=Depends(get_db)):
        return runner.cmd_init(db, payload.path, name=payload.name)

    @app.post(
        "/api/projects/{project_id}/scan",
        response_model=schemas.ScanResponse,
    )
    def scan_project(
        project_id: int,
        payload: schemas.ScanRequest,
        db=Depends(get_db),
    ):
        return runner.cmd_scan(
            db,
            project_path(db, project_id),
            reset=payload.reset,
        )

    @app.get(
        "/api/projects/{project_id}/timeline",
        response_model=schemas.TimelineResponse,
    )
    def project_timeline(project_id: int, db=Depends(get_db)):
        return schemas.TimelineResponse.from_result(
            runner.cmd_timeline(db, project_id)
        )

    @app.post(
        "/api/projects/{project_id}/translations",
        response_model=schemas.TranslationResponse,
    )
    def translate_project_commits(project_id: int, db=Depends(get_db)):
        return schemas.TranslationResponse.from_result(
            runner.cmd_translate_commits(db, project_id)
        )

    @app.get(
        "/api/llm/config",
        response_model=schemas.LLMConfigResponse,
    )
    def llm_config():
        settings = llm_settings()
        return schemas.LLMConfigResponse(
            configured=settings["configured"] == "true",
            model=settings["model"],
            base_url=settings["base_url"],
        )

    @app.get(
        "/api/projects/{project_id}/reviews",
        response_model=list[schemas.ReviewSummaryResponse],
    )
    def list_reviews(project_id: int, db=Depends(get_db)):
        path = project_path(db, project_id)
        return runner.cmd_review_list(db, path)

    @app.post(
        "/api/projects/{project_id}/reviews/generate",
        response_model=schemas.GenerateResponse,
    )
    def generate_review(
        project_id: int,
        payload: schemas.GenerateRequest,
        db=Depends(get_db),
    ):
        path = project_path(db, project_id)
        return runner.cmd_review_generate(
            db,
            path,
            since=payload.since,
            until=payload.until,
            offline=payload.offline,
        )

    @app.get(
        "/api/reviews/{draft_id}",
        response_model=schemas.ReviewDraftResponse,
    )
    def get_review_draft(draft_id: int, db=Depends(get_db)):
        record = runner.cmd_review_show(db, draft_id)
        draft = record.draft
        return schemas.ReviewDraftResponse(
            draft_id=record.draft_id,
            project_id=record.project_id,
            project_name=record.project_name,
            project_path=record.project_path,
            range_start=draft.range_start,
            range_end=draft.range_end,
            generated_at=draft.generated_at,
            exported_path=record.exported_path,
            questions=draft.questions,
            claims=[
                schemas.ReviewClaimResponse(
                    id=item.id,
                    section=item.claim.section,
                    text=item.claim.text,
                    sources=list(item.claim.sources),
                    status=item.claim.status.value,
                    user_note=item.claim.user_note,
                )
                for item in record.stored_claims
            ],
        )

    @app.post(
        "/api/reviews/{draft_id}/confirm",
        response_model=schemas.ConfirmResponse,
    )
    def confirm_review(
        draft_id: int,
        payload: schemas.ConfirmRequest,
        db=Depends(get_db),
    ):
        return runner.cmd_review_confirm(
            db,
            draft_id,
            claim_ids=payload.claim_ids,
            confirm_all=payload.confirm_all,
            note=payload.note,
        )

    @app.post(
        "/api/reviews/{draft_id}/export",
        response_model=schemas.ExportResponse,
    )
    def export_review(
        draft_id: int,
        payload: schemas.ExportRequest,
        db=Depends(get_db),
    ):
        target = runner.cmd_review_export(
            db,
            draft_id,
            output=payload.output,
        )
        return schemas.ExportResponse(path=str(target))

    @app.exception_handler(runner.CLIUsageError)
    async def usage_error_handler(request: Request, exc: runner.CLIUsageError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(GitSourceError)
    async def git_error_handler(request: Request, exc: GitSourceError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ReviewExportError)
    async def export_error_handler(request: Request, exc: ReviewExportError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(LLMError)
    async def llm_error_handler(request: Request, exc: LLMError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(DatabaseError)
    async def database_error_handler(request: Request, exc: DatabaseError):
        message = str(exc)
        not_found = "not found" in message.lower() or "不存在" in message
        return JSONResponse(
            status_code=404 if not_found else 500,
            content={"detail": message},
        )

    return app


app = create_app()
