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

# 草稿的生成方式：告诉读者这份草稿到底跑没跑 AI 归纳。
# 可复用资产只有 ai 模式才会归纳，offline 模式只生成规则骨架，
# unknown 用于本次改动之前生成的历史草稿。
GENERATION_MODE_AI = "ai"
GENERATION_MODE_OFFLINE = "offline"
GENERATION_MODE_UNKNOWN = "unknown"


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


@dataclass(frozen=True)
class ReviewQuestion:
    """一条引导问题，以及它想填上的那个板块。

    为什么要带 section：这个问题问的就是某个板块缺的内容。
    导出时答案要落回对应板块，而不是堆在文末，
    否则最后拿到的文档还是一份"只有问题没有答案"的清单。
    """

    text: str
    section: str = ""
    answer: str = ""


@dataclass
class ReviewDraft:
    """由事实、AI 论断和引导问题组装而成的完整复盘文档。"""

    project_name: str
    range_start: datetime
    range_end: datetime
    claims: list[ReviewClaim] = field(default_factory=list)
    questions: list[ReviewQuestion] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    generation_mode: str = GENERATION_MODE_UNKNOWN
