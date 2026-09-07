"""Pydantic request/response models for the DevLog HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _FromAttributes(BaseModel):
    """Base model that can be built from dataclass objects."""

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


class ExportRequest(BaseModel):
    output: str | None = None


class ExportResponse(BaseModel):
    path: str
