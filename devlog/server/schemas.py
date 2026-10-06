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
    # draft / finalized：定稿只是"这份我认了"，可以撤回。
    status: str = "draft"
    finalized_at: datetime | None = None


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
    status: str = "draft"
    finalized_at: datetime | None = None
    questions: list[ReviewQuestionResponse] = Field(default_factory=list)
    claims: list[ReviewClaimResponse] = Field(default_factory=list)


class FinalClaimResponse(BaseModel):
    """成稿里的一条陈述。status 让读者一眼分清事实、已确认和改过的。"""

    text: str
    status: str
    sources: list[str] = Field(default_factory=list)
    user_note: str = ""

    @classmethod
    def from_claim(cls, claim):
        return cls(
            text=claim.text,
            status=claim.status,
            sources=list(claim.sources),
            user_note=claim.user_note,
        )


class FinalAnswerResponse(BaseModel):
    question_number: int
    question: str
    answer: str


class FinalSectionResponse(BaseModel):
    title: str
    icon: str
    claims: list[FinalClaimResponse] = Field(default_factory=list)
    answers: list[FinalAnswerResponse] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    hint: str = ""
    count: int = 0
    is_empty: bool = True

    @classmethod
    def from_section(cls, section):
        return cls(
            title=section.title,
            icon=section.icon,
            claims=[
                FinalClaimResponse.from_claim(claim) for claim in section.claims
            ],
            answers=[
                FinalAnswerResponse(
                    question_number=answer.question_number,
                    question=answer.question,
                    answer=answer.answer,
                )
                for answer in section.answers
            ],
            open_questions=list(section.open_questions),
            hint=section.hint,
            count=section.count,
            is_empty=section.is_empty,
        )


class FinalDocumentResponse(BaseModel):
    """成稿文档：界面按它排版，Markdown 导出迟早也吃同一份数据。"""

    draft_id: int
    title: str
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    generated_at: datetime
    generation_mode: str = "unknown"
    sections: list[FinalSectionResponse] = Field(default_factory=list)
    pending: list[FinalClaimResponse] = Field(default_factory=list)
    included_count: int = 0
    pending_count: int = 0

    @classmethod
    def from_document(cls, document, *, draft_id: int, project_path: str):
        return cls(
            draft_id=draft_id,
            title=document.title,
            project_name=document.project_name,
            project_path=project_path,
            range_start=document.range_start,
            range_end=document.range_end,
            generated_at=document.generated_at,
            generation_mode=document.generation_mode,
            sections=[
                FinalSectionResponse.from_section(section)
                for section in document.sections
            ],
            pending=[
                FinalClaimResponse.from_claim(claim)
                for claim in document.pending
            ],
            included_count=document.included_count,
            pending_count=document.pending_count,
        )


class ConfirmRequest(BaseModel):
    claim_ids: list[int] = Field(default_factory=list)
    confirm_all: bool = Field(default=False, alias="all")
    note: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class ConfirmResponse(_FromAttributes):
    draft_id: int
    changed: int
    remaining_pending: int


class FinalizeRequest(BaseModel):
    """定稿或撤回定稿。定稿不锁内容，随时可以撤回继续改。"""

    finalize: bool = True


class FinalizeResponse(_FromAttributes):
    draft_id: int
    status: str
    finalized_at: datetime | None = None


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
    # 只回掩码：页面能看出"配过哪一个 key"，但拿不到明文。
    api_key_hint: str = ""
    # env / file / none：key 到底来自环境变量还是本地配置文件。
    key_source: str = "none"
    config_path: str = ""


class LLMConfigUpdate(BaseModel):
    """网页端保存大模型设置时的请求体。

    api_key / model / base_url 为 None 或空字符串时表示"这一项不动"，
    否则用户只改模型名就会顺手把密钥抹掉。API Key 要单独清除时走
    clear_api_key。
    """

    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    clear_api_key: bool = False


class LLMConfigTestResponse(BaseModel):
    ok: bool
    message: str


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


class DayCommitResponse(BaseModel):
    """当天的一次提交。"""

    short_hash: str
    subject: str
    committed_at: datetime
    files_changed: int
    insertions: int
    deletions: int

    @classmethod
    def from_day_commit(cls, item) -> "DayCommitResponse":
        return cls(
            short_hash=item.short_hash,
            subject=item.subject,
            committed_at=item.committed_at,
            files_changed=item.files_changed,
            insertions=item.insertions,
            deletions=item.deletions,
        )


class DayBugResponse(BaseModel):
    """当天捕获的一条 Bug。"""

    id: int
    title: str
    status: str
    captured_at: datetime | None

    @classmethod
    def from_day_bug(cls, item) -> "DayBugResponse":
        return cls(
            id=item.id,
            title=item.title,
            status=item.status,
            captured_at=item.captured_at,
        )


class DayDigestResponse(BaseModel):
    """某一天的事实汇总：写每日复盘前先看一眼那天到底发生了什么。"""

    day: date
    commit_count: int
    bug_count: int
    file_count: int
    insertions: int
    deletions: int
    first_commit_at: datetime | None
    last_commit_at: datetime | None
    active_minutes: int | None
    commits: list[DayCommitResponse]
    bugs: list[DayBugResponse]
    has_note: bool
    has_cached_commits: bool
    is_empty: bool
    draft_text: str

    @classmethod
    def from_digest(cls, digest) -> "DayDigestResponse":
        return cls(
            day=digest.day,
            commit_count=digest.commit_count,
            bug_count=digest.bug_count,
            file_count=digest.file_count,
            insertions=digest.insertions,
            deletions=digest.deletions,
            first_commit_at=digest.first_commit_at,
            last_commit_at=digest.last_commit_at,
            active_minutes=digest.active_minutes,
            commits=[
                DayCommitResponse.from_day_commit(item)
                for item in digest.commits
            ],
            bugs=[DayBugResponse.from_day_bug(item) for item in digest.bugs],
            has_note=digest.has_note,
            has_cached_commits=digest.has_cached_commits,
            is_empty=digest.is_empty,
            draft_text=digest.draft_text,
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
