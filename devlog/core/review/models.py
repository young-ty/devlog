"""结构化复盘草稿的数据模型。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


SECTION_OVERVIEW = "项目概述"
SECTION_TIMELINE = "开发时间线"
SECTION_DECISIONS = "技术决策记录"
SECTION_ISSUES = "问题与解决"
SECTION_LESSONS = "踩坑总结"
SECTION_ASSETS = "可复用资产"
SECTION_NEXT = "遗留与下一步"

SECTION_ORDER = [
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    SECTION_DECISIONS,
    SECTION_ISSUES,
    SECTION_LESSONS,
    SECTION_ASSETS,
    SECTION_NEXT,
]


class ClaimStatus(str, enum.Enum):
    """复盘草稿中一条论断的生命周期。"""

    FACT = "fact"
    AI_PENDING = "ai_pending"
    CONFIRMED = "confirmed"
    EDITED = "edited"


@dataclass(frozen=True)
class ReviewClaim:
    """草稿中可以独立确认的一条陈述。"""

    section: str
    text: str
    sources: tuple[str, ...] = ()
    status: ClaimStatus = ClaimStatus.AI_PENDING
    user_note: str = ""


@dataclass
class ReviewDraft:
    """由事实、AI 论断和引导问题组装而成的完整复盘文档。"""

    project_name: str
    range_start: datetime
    range_end: datetime
    claims: list[ReviewClaim] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
