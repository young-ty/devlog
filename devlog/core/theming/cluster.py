"""Deterministic rule-based theme clustering for DevLog V1.

Design notes:
- Noise commits (wip/chore/merge/revert) never enter themes, but they are
  not deleted: the caller keeps the full event list separately.
- A theme's "prototype tokens" come from the first commit's subject.
  Later commits join while they share at least one meaningful token.
- Interleaved work (A B A) produces separate themes in V1; merging is
  future work (file-overlap weighting or LLM-assisted clustering).
"""

from __future__ import annotations

import re
from datetime import timedelta

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.theming.models import ClusterResult, SilencePeriod, Theme


_CONVENTIONAL_PREFIX = re.compile(r"^([a-z]+)(?:\(([^)]*)\))?:\s*")
_MILESTONE_PATTERN = re.compile(r"^(release|milestone)(\s|:)|v?\d+\.\d+", re.IGNORECASE)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "to", "of", "in", "on",
    "add", "adding", "added", "update", "updating", "updated", "fix",
    "fixing", "fixed", "bug", "bugfix", "refactor", "refactoring", "make",
    "making", "new", "support", "enable", "enabled", "improve", "improving",
    "page", "pages", "button", "cleanup", "remove", "removed", "use", "using",
}

_KIND_BY_PREFIX = {
    "feat": "feature",
    "fix": "bugfix",
    "refactor": "refactor",
    "docs": "docs",
    "test": "test",
    "perf": "perf",
    "build": "build",
}


def _subject_tokens(subject: str) -> set[str]:
    """Return meaningful lowercase tokens from a commit subject."""

    lowered = subject.strip().lower()
    lowered = _CONVENTIONAL_PREFIX.sub("", lowered)
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", lowered)
        if len(token) >= 3 and token not in _STOPWORDS
    }
    return tokens


def _kind(subject: str) -> str:
    lowered = subject.strip().lower()
    match = _CONVENTIONAL_PREFIX.match(lowered)
    if match:
        return _KIND_BY_PREFIX.get(match.group(1), "other")
    return "other"


def _is_milestone_subject(subject: str) -> bool:
    return bool(_MILESTONE_PATTERN.search(subject))


def cluster_themes(
    events: list[CommitEvent],
    silence_threshold_days: int = 3,
) -> ClusterResult:
    """Group non-noise commits into themes and report silence periods.

    Noise commits are ignored for clustering and for silence detection,
    so a wip in the middle of one feature does not split the theme.
    """

    meaningful = [
        event for event in events if event.noise_type == NoiseType.NONE
    ]
    meaningful.sort(key=lambda event: (event.committed_at, event.short_hash))

    themes: list[Theme] = []
    silence_periods: list[SilencePeriod] = []

    current_theme: list[CommitEvent] | None = None
    prototype_tokens: set[str] = set()

    previous: CommitEvent | None = None
    for event in meaningful:
        if previous is not None and event.committed_at > previous.committed_at:
            elapsed = event.committed_at - previous.committed_at
            if elapsed > timedelta(days=silence_threshold_days):
                silence_periods.append(
                    SilencePeriod(
                        started_at=previous.committed_at,
                        ended_at=event.committed_at,
                        days=elapsed.days,
                    )
                )
        previous = event

        tokens = _subject_tokens(event.message_subject)
        joined = (
            current_theme is not None
            and bool(tokens & prototype_tokens)
        )
        if current_theme is None or not joined:
            if current_theme:
                themes.append(_build_theme(len(themes) + 1, current_theme))
            current_theme = [event]
            prototype_tokens = tokens
        else:
            current_theme.append(event)
            prototype_tokens = prototype_tokens | tokens

    if current_theme:
        themes.append(_build_theme(len(themes) + 1, current_theme))

    return ClusterResult(themes=themes, silence_periods=silence_periods)


def _build_theme(theme_number: int, commits: list[CommitEvent]) -> Theme:
    first = commits[0]
    tokens = _subject_tokens(first.message_subject)
    title = " ".join(sorted(tokens)) if tokens else first.message_subject
    hashes = tuple(event.hash for event in commits)
    is_milestone = any(
        _is_milestone_subject(event.message_subject) for event in commits
    )
    return Theme(
        id=f"theme-{theme_number}",
        title=title,
        kind=_kind(first.message_subject),
        commit_hashes=hashes,
        started_at=commits[0].committed_at,
        ended_at=commits[-1].committed_at,
        commit_count=len(commits),
        is_milestone_candidate=is_milestone,
    )
