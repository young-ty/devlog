"""Data models produced by theme clustering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Theme:
    """A group of commits that tell one part of the project story."""

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
    """A gap between non-noise commits worth asking about in a review."""

    started_at: datetime
    ended_at: datetime
    days: int


@dataclass(frozen=True)
class ClusterResult:
    """Everything derived from one clustering pass."""

    themes: list[Theme]
    silence_periods: list[SilencePeriod]
