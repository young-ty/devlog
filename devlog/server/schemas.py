"""DevLog HTTP API 的 Pydantic 请求/响应模型。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class _FromAttributes(BaseModel):
    """可从 dataclass 对象构建的基类模型。"""

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    path: str
    name: str | None = None


class ProjectListResponse(_FromAttributes):
    project_id: int
    name: str
    path: str
    created_at: datetime
    last_scanned_commit: str | None = None


class InitResponse(_FromAttributes):
    project_id: int
    project_name: str
    project_path: str


class DirectoryPickResponse(BaseModel):
    """系统文件夹选择框的结果。

    cancelled 表示用户点了取消 —— 这是正常结果，前端静默处理即可；
    is_git_repo 让前端在选完就能提示"这里不是 Git 仓库"，
    不用等注册失败才发现。
    """

    cancelled: bool = False
    path: str | None = None
    is_git_repo: bool = False


class ScanRequest(BaseModel):
    reset: bool = False


class ScanResponse(_FromAttributes):
    project_id: int
    project_name: str
    project_path: str
    total_events: int
    inserted_events: int
    reset: bool


class GenerateRequest(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    offline: bool = False


class GenerateResponse(_FromAttributes):
    draft_id: int
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    claim_count: int
    ai_pending_count: int
    question_count: int
    asset_count: int
    offline: bool


class ReviewSummaryResponse(_FromAttributes):
    draft_id: int
    project_id: int
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    created_at: datetime
    total_claims: int
    ai_pending_claims: int
    confirmed_claims: int
    # ai / offline / unknown：列表里要能标出旧版本生成的草稿。
    generation_mode: str = "unknown"


class ReviewClaimResponse(BaseModel):
    id: int
    section: str
    text: str
    sources: list[str] = Field(default_factory=list)
    status: str
    user_note: str = ""


class ReviewQuestionResponse(BaseModel):
    """一条引导问题：问的是什么、对应哪个板块、用户补充了什么。"""

    text: str
    section: str = ""
    answer: str = ""


class ReviewDraftResponse(BaseModel):
    draft_id: int
    project_id: int
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    generated_at: datetime
    generation_mode: str = "unknown"
    exported_path: str | None = None
    questions: list[ReviewQuestionResponse] = Field(default_factory=list)
    claims: list[ReviewClaimResponse] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    claim_ids: list[int] = Field(default_factory=list)
    confirm_all: bool = Field(default=False, alias="all")
    note: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class ConfirmResponse(_FromAttributes):
    draft_id: int
    changed: int
    remaining_pending: int


class AnswerRequest(BaseModel):
    """引导问题的回答；空字符串表示清空。"""

    answer: str = ""


class TimelineCommitResponse(BaseModel):
    hash: str
    short_hash: str
    author_name: str
    author_email: str
    committed_at: datetime
    message_subject: str
    files_changed: int
    insertions: int
    deletions: int
    parents_count: int
    noise_type: str
    translated_subject: str | None = None


class TimelineThemeResponse(BaseModel):
    id: str
    title: str
    kind: str
    commit_hashes: list[str]
    started_at: datetime
    ended_at: datetime
    commit_count: int
    is_milestone_candidate: bool

    @classmethod
    def from_theme(cls, theme) -> "TimelineThemeResponse":
        return cls(
            id=theme.id,
            title=theme.title,
            kind=theme.kind,
            commit_hashes=list(theme.commit_hashes),
            started_at=theme.started_at,
            ended_at=theme.ended_at,
            commit_count=theme.commit_count,
            is_milestone_candidate=theme.is_milestone_candidate,
        )


class TimelineSilenceResponse(BaseModel):
    started_at: datetime
    ended_at: datetime
    days: int

    @classmethod
    def from_period(cls, period) -> "TimelineSilenceResponse":
        return cls(
            started_at=period.started_at,
            ended_at=period.ended_at,
            days=period.days,
        )


class TimelineResponse(BaseModel):
    project_id: int
    project_name: str
    project_path: str
    range_start: datetime | None = None
    range_end: datetime | None = None
    commits: list[TimelineCommitResponse] = Field(default_factory=list)
    themes: list[TimelineThemeResponse] = Field(default_factory=list)
    silence_periods: list[TimelineSilenceResponse] = Field(
        default_factory=list
    )

    @classmethod
    def from_result(cls, result):
        translations = getattr(result, "translations", {})
        return cls(
            project_id=result.project_id,
            project_name=result.project_name,
            project_path=result.project_path,
            range_start=result.range_start,
            range_end=result.range_end,
            commits=[
                TimelineCommitResponse(
                    **event.to_dict(),
                    translated_subject=translations.get(event.hash),
                )
                for event in result.commits
            ],
            themes=[
                TimelineThemeResponse.from_theme(theme)
                for theme in result.themes
            ],
            silence_periods=[
                TimelineSilenceResponse.from_period(period)
                for period in result.silence_periods
            ],
        )


class TranslationResponse(BaseModel):
    project_id: int
    project_name: str
    project_path: str
    translated_count: int
    remaining_count: int

    @classmethod
    def from_result(cls, result):
        return cls(
            project_id=result.project_id,
            project_name=result.project_name,
            project_path=result.project_path,
            translated_count=result.translated_count,
            remaining_count=result.remaining_count,
        )


class LLMConfigResponse(BaseModel):
    configured: bool
    model: str
    base_url: str


class ExportRequest(BaseModel):
    output: str | None = None


class ExportResponse(BaseModel):
    path: str


class DailyNoteRequest(BaseModel):
    note_date: date
    summary: str = ""
    issues: str = ""
    plan: str = ""


class DailyNoteResponse(BaseModel):
    id: int
    project_id: int
    note_date: date
    summary: str
    issues: str
    plan: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_stored(cls, stored) -> "DailyNoteResponse":
        note = stored.note
        return cls(
            id=stored.id,
            project_id=stored.project_id,
            note_date=note.note_date,
            summary=note.summary,
            issues=note.issues,
            plan=note.plan,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )


class BugCaptureRequest(BaseModel):
    title: str | None = None
    title_source: str = "manual"
    error_text: str = ""


class BugUpdateRequest(BaseModel):
    title: str | None = None
    title_source: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    status: str | None = None


class BugResponse(BaseModel):
    id: int
    project_id: int
    title: str
    title_source: str
    error_text: str
    environment: str
    git_head: str
    git_status: str
    status: str
    root_cause: str
    solution: str
    captured_at: datetime
    updated_at: datetime

    @classmethod
    def from_stored(cls, stored) -> "BugResponse":
        bug = stored.bug
        return cls(
            id=stored.id,
            project_id=stored.project_id,
            title=bug.title,
            title_source=bug.title_source,
            error_text=bug.error_text,
            environment=bug.environment,
            git_head=bug.git_head,
            git_status=bug.git_status,
            status=bug.status.value,
            root_cause=bug.root_cause,
            solution=bug.solution,
            captured_at=stored.captured_at,
            updated_at=stored.updated_at,
        )


class BugSuggestTitleRequest(BaseModel):
    error_text: str
    environment: str = ""


class BugSuggestTitleResponse(BaseModel):
    title: str


class AnnotationCreateRequest(BaseModel):
    kind: str = "note"
    body: str


class AnnotationUpdateRequest(BaseModel):
    kind: str | None = None
    body: str | None = None


class AnnotationResponse(BaseModel):
    id: int
    project_id: int
    commit_hash: str
    kind: str
    body: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_stored(cls, stored) -> "AnnotationResponse":
        annotation = stored.annotation
        return cls(
            id=stored.id,
            project_id=stored.project_id,
            commit_hash=annotation.commit_hash,
            kind=annotation.kind.value,
            body=annotation.body,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )


class TimelineEventResponse(BaseModel):
    """时间线上的一个节点。payload 字段按 kind 取用。

    前端拿到之后先看 kind，再决定读哪个字段 —— 提交有 hash、Bug 有
    状态、笔记只有日期，用一个可选字段组装下比六种子类型更容易渲染。
    """

    kind: str
    at: datetime
    key: str
    commit: TimelineCommitResponse | None = None
    bug: BugResponse | None = None
    note: DailyNoteResponse | None = None
    annotation: AnnotationResponse | None = None
    theme: TimelineThemeResponse | None = None
    gap: TimelineSilenceResponse | None = None

    @classmethod
    def from_event(cls, event, translations) -> "TimelineEventResponse":
        return cls(
            kind=event.kind.value,
            at=event.at,
            key=event.key,
            commit=(
                TimelineCommitResponse(
                    **event.commit.to_dict(),
                    translated_subject=translations.get(event.commit.hash),
                )
                if event.commit is not None
                else None
            ),
            bug=(
                BugResponse.from_stored(event.bug)
                if event.bug is not None
                else None
            ),
            note=(
                DailyNoteResponse.from_stored(event.note)
                if event.note is not None
                else None
            ),
            annotation=(
                AnnotationResponse.from_stored(event.annotation)
                if event.annotation is not None
                else None
            ),
            theme=(
                TimelineThemeResponse.from_theme(event.theme)
                if event.theme is not None
                else None
            ),
            gap=(
                TimelineSilenceResponse.from_period(event.gap)
                if event.gap is not None
                else None
            ),
        )


class TimelineEventsResponse(BaseModel):
    """合并后的时间线事件流。"""

    project_id: int
    project_name: str
    project_path: str
    total_count: int
    truncated_count: int
    orphan_annotation_count: int
    events: list[TimelineEventResponse] = Field(default_factory=list)

    @classmethod
    def from_result(cls, result) -> "TimelineEventsResponse":
        translations = getattr(result, "translations", {})
        return cls(
            project_id=result.project_id,
            project_name=result.project_name,
            project_path=result.project_path,
            total_count=result.total_count,
            truncated_count=result.truncated_count,
            orphan_annotation_count=result.orphan_annotation_count,
            events=[
                TimelineEventResponse.from_event(event, translations)
                for event in result.events
            ],
        )
