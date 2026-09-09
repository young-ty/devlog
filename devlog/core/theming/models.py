"""主题聚类产生的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Theme:
    """一组共同讲述项目某段故事的 commit。"""

    id: str
    title: str
    kind: str
    commit_hashes: tuple[str, ...]
    started_at: datetime
    ended_at: datetime
    commit_count: int
    is_milestone_candidate: bool = False


@dataclass(frozen=True)
class SilencePeriod:
    """非噪音 commit 之间值得在复盘中追问的空档期。"""

    started_at: datetime
    ended_at: datetime
    days: int


@dataclass(frozen=True)
class ClusterResult:
    """一次完整聚类得到的所有结果。"""

    themes: list[Theme]
    silence_periods: list[SilencePeriod]
