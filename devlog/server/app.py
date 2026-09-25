"""把 runner 封装成 HTTP 接口的 FastAPI 应用。

这里不写业务逻辑：路由只把 HTTP 请求翻译成 runner 调用，
和 cli/main.py 处理终端输入的方式完全一致。
"""

from __future__ import annotations

import ipaddress
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from devlog.cli import runner
from devlog.core.capture.models import AnnotationKind, BugStatus, DailyNote
from devlog.core.git_source.scanner import GitSourceError
from devlog.core.llm.deepseek import llm_settings
from devlog.core.llm.base import LLMError
from devlog.core.review.markdown import ReviewExportError
from devlog.core.storage.database import DevLogDB, DatabaseError, default_db_path
from devlog.core.timeline.events import DEFAULT_EVENT_LIMIT
from devlog.server import desktop, schemas
from devlog.server.static_cache import CacheControlledStatic


# 前端构建产物默认位置：devlog/web/dist（由 `pnpm build` 生成）。
DEFAULT_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def resolve_web_dist(web_dir: str | Path | None = None) -> Path | None:
    """返回可用的前端构建目录；没有构建产物时返回 None（退化成纯 API 模式）。

    只认「目录里真的有 index.html」这一条判据，避免把空目录当成
    可用的前端产物，让用户看到一个打不开的页面。
    """

    candidate = (
        Path(web_dir).expanduser() if web_dir is not None else DEFAULT_WEB_DIST
    )
    if (candidate / "index.html").is_file():
        return candidate
    return None


def _parse_bug_status(value: str) -> BugStatus:
    """把状态字符串转成枚举；不在可选值里时给友好的 400 提示。"""

    try:
        return BugStatus(value)
    except ValueError:
        choices = "、".join(item.value for item in BugStatus)
        raise runner.CLIUsageError(
            f"未知的 Bug 状态：{value}（可选：{choices}）"
        )


def _parse_annotation_kind(value: str) -> AnnotationKind:
    """把批注类型字符串转成枚举；不在可选值里时给友好的 400 提示。"""

    try:
        return AnnotationKind(value)
    except ValueError:
        choices = "、".join(item.value for item in AnnotationKind)
        raise runner.CLIUsageError(
            f"未知的批注类型：{value}（可选：{choices}）"
        )


def is_loopback_request(request: Request) -> bool:
    """请求是不是来自本机（127.0.0.1 / ::1 / localhost）。

    文件夹选择框会在服务器所在电脑上弹出一个可见窗口，
    是典型的"本机特权"。如果用户用 --host 0.0.0.0 把服务暴露到局域网，
    必须确保外面的人不能远程指挥你的桌面弹窗。
    判定不出来来源时一律拒绝（fail closed）。
    """

    client = request.client
    if client is None:
        return False
    host = client.host
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(
    db_path: str | Path | None = None,
    web_dir: str | Path | None = None,
    directory_picker: Callable[[], str | None] | None = None,
) -> FastAPI:
    """构建配置好的 DevLog API 应用（供 uvicorn 与测试使用）。

    如果 `devlog/web/dist` 里有前端构建产物，就把静态文件挂到根路径，
    这样一个端口同时提供页面和 API；没有产物时只提供 API，
    开发期继续用 `pnpm dev` 的 5173 端口。

    `directory_picker` 默认调用本机系统对话框；测试时注入假实现，
    这样跑测试不会真的弹出窗口。
    """

    resolved_db = (
        str(Path(db_path).expanduser().resolve())
        if db_path is not None
        else str(default_db_path())
    )
    web_dist = resolve_web_dist(web_dir)
    picker = directory_picker or desktop.pick_directory
    app = FastAPI(
        title="DevLog API",
        description="本地开发复盘工具的 HTTP 接口",
        version="0.1.0",
    )
    app.state.db_path = resolved_db
    app.state.web_dist = str(web_dist) if web_dist is not None else None

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
        "/api/system/pick-directory",
        response_model=schemas.DirectoryPickResponse,
    )
    def pick_directory(request: Request):
        """弹出系统文件夹选择框，把用户选中的路径回给网页。"""

        if not is_loopback_request(request):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "文件夹选择框只对本机请求开放。"
                    "请在本机浏览器打开 DevLog，或手动填写仓库路径。"
                },
            )
        try:
            picked = picker()
        except desktop.DirectoryPickerBusy as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})
        except desktop.DirectoryPickerError as exc:
            return JSONResponse(status_code=503, content={"detail": str(exc)})

        if not picked:
            return schemas.DirectoryPickResponse(cancelled=True)
        path = Path(picked).expanduser()
        return schemas.DirectoryPickResponse(
            path=str(path),
            is_git_repo=runner.is_git_repo(path),
        )

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

    @app.get(
        "/api/projects/{project_id}/timeline-events",
        response_model=schemas.TimelineEventsResponse,
    )
    def project_timeline_events(
        project_id: int,
        limit: int | None = DEFAULT_EVENT_LIMIT,
        db=Depends(get_db),
    ):
        """合并提交、Bug、笔记、批注、里程碑与空档，返回排好序的事件流。"""

        return schemas.TimelineEventsResponse.from_result(
            runner.cmd_timeline_events(db, project_id, limit=limit)
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
        "/api/reviews/{draft_id}/document",
        response_model=schemas.FinalDocumentResponse,
    )
    def get_review_document(draft_id: int, db=Depends(get_db)):
        result = runner.cmd_review_document(db, draft_id)
        return schemas.FinalDocumentResponse.from_document(
            result.document,
            draft_id=result.record.draft_id,
            project_path=result.record.project_path,
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
            generation_mode=draft.generation_mode,
            exported_path=record.exported_path,
            questions=[
                schemas.ReviewQuestionResponse(
                    text=question.text,
                    section=question.section,
                    answer=question.answer,
                )
                for question in draft.questions
            ],
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

    @app.put(
        "/api/reviews/{draft_id}/answers/{question_number}",
        response_model=schemas.ReviewQuestionResponse,
    )
    def save_review_answer(
        draft_id: int,
        question_number: int,
        payload: schemas.AnswerRequest,
        db=Depends(get_db),
    ):
        """保存引导问题的回答；编号从 1 开始，与页面显示一致。"""

        question = runner.cmd_review_answer(
            db,
            draft_id,
            question_number,
            payload.answer,
        )
        return schemas.ReviewQuestionResponse(
            text=question.text,
            section=question.section,
            answer=question.answer,
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

    @app.delete("/api/reviews/{draft_id}")
    def delete_review(draft_id: int, db=Depends(get_db)):
        """删除草稿。不存在返回 404，避免前端把"没删掉"当成成功。"""

        if not runner.cmd_review_delete(db, draft_id):
            raise HTTPException(
                status_code=404, detail=f"草稿不存在：{draft_id}"
            )
        return {"deleted": True}

    # ------------------------------------------------------------------
    # 记忆层：每日笔记
    # ------------------------------------------------------------------

    @app.get(
        "/api/projects/{project_id}/notes",
        response_model=list[schemas.DailyNoteResponse],
    )
    def list_notes(
        project_id: int,
        note_date: date | None = None,
        db=Depends(get_db),
    ):
        # 先校验项目存在；项目不存在时抛出 404
        project_path(db, project_id)
        notes = runner.cmd_daily_note_list(
            db,
            project_id,
            since=note_date,
            until=note_date,
        )
        return [schemas.DailyNoteResponse.from_stored(item) for item in notes]

    @app.post(
        "/api/projects/{project_id}/notes",
        response_model=schemas.DailyNoteResponse,
    )
    def save_note(
        project_id: int,
        payload: schemas.DailyNoteRequest,
        db=Depends(get_db),
    ):
        project_path(db, project_id)
        stored = runner.cmd_daily_note_save(
            db,
            project_id,
            DailyNote(
                note_date=payload.note_date,
                summary=payload.summary,
                issues=payload.issues,
                plan=payload.plan,
            ),
        )
        return schemas.DailyNoteResponse.from_stored(stored)

    # ------------------------------------------------------------------
    # 记忆层：Bug 捕获
    # ------------------------------------------------------------------

    @app.get(
        "/api/projects/{project_id}/bugs",
        response_model=list[schemas.BugResponse],
    )
    def list_bugs(
        project_id: int,
        status: str | None = None,
        db=Depends(get_db),
    ):
        project_path(db, project_id)
        parsed_status = (
            _parse_bug_status(status) if status is not None else None
        )
        records = runner.cmd_bug_list(
            db,
            project_id,
            status=parsed_status,
        )
        return [schemas.BugResponse.from_stored(item) for item in records]

    @app.post(
        "/api/projects/{project_id}/bugs",
        response_model=schemas.BugResponse,
        status_code=201,
    )
    def capture_bug(
        project_id: int,
        payload: schemas.BugCaptureRequest,
        db=Depends(get_db),
    ):
        stored = runner.cmd_bug_capture(
            db,
            project_id,
            title=payload.title or "",
            error_text=payload.error_text,
            title_source=payload.title_source,
        )
        return schemas.BugResponse.from_stored(stored)

    @app.patch("/api/bugs/{bug_id}", response_model=schemas.BugResponse)
    def update_bug(
        bug_id: int,
        payload: schemas.BugUpdateRequest,
        db=Depends(get_db),
    ):
        if (
            payload.title is None
            and payload.title_source is None
            and payload.root_cause is None
            and payload.solution is None
            and payload.status is None
        ):
            raise runner.CLIUsageError("至少提供一个要修改的字段")
        if (
            payload.title_source is not None
            and payload.title_source not in {"manual", "ai"}
        ):
            raise runner.CLIUsageError(
                f"未知的标题来源：{payload.title_source}"
                "（可选：manual、ai）"
            )
        parsed_status = (
            _parse_bug_status(payload.status)
            if payload.status is not None
            else None
        )
        stored = runner.cmd_bug_update(
            db,
            bug_id,
            title=payload.title,
            title_source=payload.title_source,
            root_cause=payload.root_cause,
            solution=payload.solution,
            status=parsed_status,
        )
        return schemas.BugResponse.from_stored(stored)

    @app.delete("/api/bugs/{bug_id}")
    def delete_bug(bug_id: int, db=Depends(get_db)):
        return {"deleted": runner.cmd_bug_delete(db, bug_id)}

    @app.post(
        "/api/bugs/suggest-title",
        response_model=schemas.BugSuggestTitleResponse,
    )
    def suggest_bug_title(payload: schemas.BugSuggestTitleRequest):
        title = runner.cmd_suggest_bug_title(
            payload.error_text,
            payload.environment,
        )
        return schemas.BugSuggestTitleResponse(title=title)

    # ------------------------------------------------------------------
    # 记忆层：commit 批注
    # ------------------------------------------------------------------

    @app.post(
        "/api/projects/{project_id}/commits/{commit_hash}/annotations",
        response_model=schemas.AnnotationResponse,
        status_code=201,
    )
    def add_annotation(
        project_id: int,
        commit_hash: str,
        payload: schemas.AnnotationCreateRequest,
        db=Depends(get_db),
    ):
        project_path(db, project_id)
        stored = runner.cmd_annotation_add(
            db,
            project_id,
            commit_hash,
            _parse_annotation_kind(payload.kind),
            payload.body,
        )
        return schemas.AnnotationResponse.from_stored(stored)

    @app.get(
        "/api/projects/{project_id}/annotations",
        response_model=list[schemas.AnnotationResponse],
    )
    def list_annotations(
        project_id: int,
        commit_hash: str | None = None,
        orphan: bool = False,
        db=Depends(get_db),
    ):
        project_path(db, project_id)
        annotations = runner.cmd_annotation_list(
            db,
            project_id,
            commit_hash=commit_hash,
            orphan=orphan,
        )
        return [
            schemas.AnnotationResponse.from_stored(item)
            for item in annotations
        ]

    @app.patch(
        "/api/annotations/{annotation_id}",
        response_model=schemas.AnnotationResponse,
    )
    def update_annotation(
        annotation_id: int,
        payload: schemas.AnnotationUpdateRequest,
        db=Depends(get_db),
    ):
        if payload.kind is None and payload.body is None:
            raise runner.CLIUsageError("至少提供一个要修改的字段")
        parsed_kind = (
            _parse_annotation_kind(payload.kind)
            if payload.kind is not None
            else None
        )
        stored = runner.cmd_annotation_update(
            db,
            annotation_id,
            kind=parsed_kind,
            body=payload.body,
        )
        return schemas.AnnotationResponse.from_stored(stored)

    @app.delete("/api/annotations/{annotation_id}")
    def delete_annotation(annotation_id: int, db=Depends(get_db)):
        return {"deleted": runner.cmd_annotation_delete(db, annotation_id)}

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
        not_found = (
            "not found" in message.lower()
            or "不存在" in message
            or "not cached" in message.lower()
        )
        return JSONResponse(
            status_code=404 if not_found else 500,
            content={"detail": message},
        )

    # 静态资源必须最后挂载：路由按注册顺序匹配，放前面会把 /api/** 一起吞掉。
    if web_dist is not None:
        app.mount(
            "/",
            CacheControlledStatic(StaticFiles(directory=web_dist, html=True)),
            name="web",
        )

    return app


app = create_app()
