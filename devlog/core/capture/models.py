"""Domain models for the daily-note / bug-capture memory layer.

Git events answer "what was committed"; these records answer "what did I
learn or hit while working" and are always written by the human (or
AI-suggested and then human-confirmed) rather than derived from Git.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date


class BugStatus(str, enum.Enum):
    """Lifecycle of one captured bug record."""

    OPEN = "open"
    ROOT_CAUSE_FOUND = "root_cause_found"
    RESOLVED = "resolved"


class AnnotationKind(str, enum.Enum):
    """Type of a note anchored to one commit."""

    NOTE = "note"
    DECISION = "decision"


@dataclass(frozen=True)
class DailyNote:
    """Human-written recap for one project on one calendar date."""

    note_date: date
    summary: str = ""
    issues: str = ""
    plan: str = ""


@dataclass(frozen=True)
class BugRecord:
    """A scene snapshot captured when a bug appears, plus later answers."""

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
    """A lightweight note anchored to one commit of one project."""

    commit_hash: str
    kind: AnnotationKind = AnnotationKind.NOTE
    body: str = ""
