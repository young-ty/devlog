"""DevLog Git 扫描产生的 commit 事件数据模型。"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class NoiseType(str, enum.Enum):
    """为什么某条 commit 应被视为低信号噪音。"""

    NONE = "none"
    MERGE = "merge"
    REVERT = "revert"
    WIP = "wip"
    CHORE = "chore"


@dataclass(frozen=True)
class CommitEvent:
    """一条规范化的 commit，不依赖 Git 内部实现细节。"""

    hash: str
    short_hash: str
    author_name: str
    author_email: str
    committed_at: datetime
    message_subject: str
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    parents_count: int = 0
    noise_type: NoiseType = NoiseType.NONE

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 或 SQLite 存储所需的结构。"""

        return {
            "hash": self.hash,
            "short_hash": self.short_hash,
            "author_name": self.author_name,
            "author_email": self.author_email,
            "committed_at": self.committed_at.isoformat(),
            "message_subject": self.message_subject,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "parents_count": self.parents_count,
            "noise_type": self.noise_type.value,
        }

    def __str__(self) -> str:
        when = self.committed_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.short_hash} {when} {self.message_subject}"
