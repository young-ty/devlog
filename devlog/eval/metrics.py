"""主题摘要的确定性评分指标。

所有函数都是纯函数：不调用 API、不访问文件系统，因此可以单元测试，
并能在 CI 中离线运行。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devlog.core.llm.themes import ThemeSummary


_CJK = r"\u4e00-\u9fff"
_TOKEN_PATTERN = re.compile(rf"[a-z0-9]+|[{_CJK}]")


def token_set(text: str) -> set[str]:
    """把中文文本拆成小写拉丁词元加中文字符的集合。"""

    lowered = text.lower()
    return set(_TOKEN_PATTERN.findall(lowered))


def dice_coverage(candidate: str, gold: str) -> float:
    """词元集合上的 Dice 系数；1.0 表示词元集合完全相同。"""

    left = token_set(candidate)
    right = token_set(gold)
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return round(2.0 * overlap / (len(left) + len(right)), 4)


def source_precision(candidate: tuple[str, ...], actual: tuple[str, ...]) -> float:
    """候选摘要引用的来源中，确实属于该主题的比例（精确率）。"""

    claimed = set(candidate)
    real = set(actual)
    if not claimed:
        return 0.0
    return round(len(claimed & real) / len(claimed), 4)


def source_recall(candidate: tuple[str, ...], actual: tuple[str, ...]) -> float:
    """该主题真实来源中，摘要成功引用到的比例（召回率）。"""

    claimed = set(candidate)
    real = set(actual)
    if not real:
        return 1.0
    return round(len(claimed & real) / len(real), 4)


def kind_score(candidate: ThemeSummary, gold: ThemeSummary) -> float:
    """类型相同时为 1.0，否则为 0.0。"""

    return 1.0 if candidate.kind.strip().lower() == gold.kind.strip().lower() else 0.0


@dataclass(frozen=True)
class SummaryMetrics:
    coverage: float
    source_precision: float
    source_recall: float
    kind_score: float
    overall: float


def evaluate_summary(
    candidate: ThemeSummary,
    gold: ThemeSummary,
) -> SummaryMetrics:
    """给一份候选摘要对照一条人工标准答案打分。"""

    coverage = dice_coverage(candidate.summary, gold.summary)
    precision = source_precision(candidate.sources, gold.sources)
    recall = source_recall(candidate.sources, gold.sources)
    kind = kind_score(candidate, gold)
    overall = round(
        0.5 * coverage
        + 0.15 * precision
        + 0.15 * recall
        + 0.2 * kind,
        4,
    )
    return SummaryMetrics(
        coverage=coverage,
        source_precision=precision,
        source_recall=recall,
        kind_score=kind,
        overall=overall,
    )
