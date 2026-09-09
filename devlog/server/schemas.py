"""DevLog HTTP API 的 Pydantic 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

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


class ReviewClaimResponse(BaseModel):
    id: int
    section: str
    text: str
    sources: list[str] = Field(default_factory=list)
    status: str
    user_note: str = ""


class ReviewDraftResponse(BaseModel):
    draft_id: int
    project_id: int
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    generated_at: datetime
    exported_path: str | None = None
    questions: list[str] = Field(default_factory=list)
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


class TimelineSilenceResponse(BaseModel):
    started_at: datetime
    ended_at: datetime
    days: int


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
                TimelineThemeResponse(
                    id=theme.id,
                    title=theme.title,
                    kind=theme.kind,
                    commit_hashes=list(theme.commit_hashes),
                    started_at=theme.started_at,
                    ended_at=theme.ended_at,
                    commit_count=theme.commit_count,
                    is_milestone_candidate=theme.is_milestone_candidate,
                )
                for theme in result.themes
            ],
            silence_periods=[
                TimelineSilenceResponse(
                    started_at=period.started_at,
                    ended_at=period.ended_at,
                    days=period.days,
                )
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
