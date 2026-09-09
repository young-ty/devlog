"""DevLog V1 的确定性规则版主题聚类。

设计说明：
- 噪音 commit（wip/chore/merge/revert）永远不进入主题，但不会被删除：
  调用方另行保留完整事件列表。
- 主题的“原型词元”来自第一条 commit 的 subject；后续 commit 只要与
  原型词元共享至少一个有意义词元就加入该主题。
- 交错开发（A B A）在 V1 中会产生多个独立主题；合并是未来工作
  （文件重叠权重或 LLM 辅助聚类）。
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
    """从 commit subject 中提取有意义的小写词元。"""

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
    """把非噪音 commit 分组成主题，并报告静默期。

    聚类与静默期检测都会忽略噪音 commit，因此某个功能中间的 wip
    不会把主题拆开。
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
