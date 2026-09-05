"""Commit event data models for DevLog git scanning."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class NoiseType(str, enum.Enum):
    """Why a commit should be treated as low-signal noise."""

    NONE = "none"
    MERGE = "merge"
    REVERT = "revert"
    WIP = "wip"
    CHORE = "chore"


@dataclass(frozen=True)
class CommitEvent:
    """One normalized commit, independent of git internals."""

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
        """Serialize for JSON or SQLite storage."""

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
