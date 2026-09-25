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
# 连续的中日韩字符片段。中文提交没有空格，不能像英文那样按分隔符切词。
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "to", "of", "in", "on",
    "add", "adding", "added", "update", "updating", "updated", "fix",
    "fixing", "fixed", "bug", "bugfix", "refactor", "refactoring", "make",
    "making", "new", "support", "enable", "enabled", "improve", "improving",
    "page", "pages", "button", "cleanup", "remove", "removed", "use", "using",
}

# 中文提交里的高频动作词。取 2 字滑窗后，这些词会让两条不相干的提交
# 因为"都写了新增/修复"而被错并成一个主题，所以按噪音去掉 ——
# 和英文停用词里已经有 add / fix / update 是同一个道理。
_CJK_STOPWORDS = {
    "新增", "添加", "增加", "修复", "修復", "修改", "优化", "调整", "更新",
    "支持", "完善", "补充", "实现", "删除", "移除", "重构", "整理", "升级",
    "改进", "提升", "解决", "处理", "完成", "测试", "文档", "配置", "接入",
    "使用", "改为", "换成", "发布", "版本", "内容", "相关", "问题", "功能",
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
    tokens |= _cjk_tokens(lowered)
    return tokens


def _cjk_tokens(text: str) -> set[str]:
    """把中文片段切成 2 字滑窗词元。

    为什么不引入 jieba 之类的分词器：V1 要零依赖、结果可复现，而聚类
    只需要判断"两条提交是不是在聊同一件事"，bigram 这种粗粒度已经够用；
    滑窗切出来的"增菜"这类碎片会被停用词和"取交集"的规则稀释掉。
    """

    tokens: set[str] = set()
    for run in _CJK_PATTERN.findall(text):
        if len(run) == 1:
            tokens.add(run)
            continue
        for index in range(len(run) - 1):
            token = run[index : index + 2]
            if token not in _CJK_STOPWORDS:
                tokens.add(token)
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
    title = _theme_title(first.message_subject)
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


def _theme_title(subject: str) -> str:
    """给主题起一个能进提示词的标题。

    英文提交用关键词集合（"login payment"）；中文提交的 bigram 词元拼出来
    是"接口 推荐 新增"这种碎片，当标题不好读，也会污染 AI 摘要的提示词，
    所以中文直接用去掉约定前缀的原句。
    """

    if _CJK_PATTERN.search(subject):
        cleaned = _CONVENTIONAL_PREFIX.sub("", subject.strip()).strip()
        return cleaned or subject.strip()
    tokens = _subject_tokens(subject)
    return " ".join(sorted(tokens)) if tokens else subject.strip()
