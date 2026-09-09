"""每日笔记 / Bug 捕获 / commit 批注记忆层的领域模型。

Git 事件回答“提交了什么”；这些记录回答“开发时遇到了什么、学到了什么”，
始终由人书写（或由 AI 建议、经人确认后采用），而不是从 Git 推导。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date


class BugStatus(str, enum.Enum):
    """一条已捕获 Bug 记录的生命周期。"""

    OPEN = "open"
    ROOT_CAUSE_FOUND = "root_cause_found"
    RESOLVED = "resolved"


class AnnotationKind(str, enum.Enum):
    """挂在某条 commit 上的批注类型。"""

    NOTE = "note"
    DECISION = "decision"


@dataclass(frozen=True)
class DailyNote:
    """一个人针对某个项目在某个日历日期写下的复盘。"""

    note_date: date
    summary: str = ""
    issues: str = ""
    plan: str = ""


@dataclass(frozen=True)
class BugRecord:
    """Bug 出现时捕获的现场快照，以及事后补充的答案。"""

    title: str
    error_text: str = ""
    environment: str = ""
    git_head: str = ""
    git_status: str = ""
    title_source: str = "manual"
    status: BugStatus = BugStatus.OPEN
    root_cause: str = ""
    solution: str = ""


@dataclass(frozen=True)
class CommitAnnotation:
    """挂在某项目某条 commit 上的轻量批注。"""

    commit_hash: str
    kind: AnnotationKind = AnnotationKind.NOTE
    body: str = ""
