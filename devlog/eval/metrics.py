"""Deterministic scoring metrics for theme summaries.

All functions are pure: no API calls, no filesystem access, so they can be
unit-tested and run offline in CI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devlog.core.llm.themes import ThemeSummary


_CJK = r"\u4e00-\u9fff"
_TOKEN_PATTERN = re.compile(rf"[a-z0-9]+|[{_CJK}]")


def token_set(text: str) -> set[str]:
    """Split Chinese text into lower-case latin words plus CJK characters."""

    lowered = text.lower()
    return set(_TOKEN_PATTERN.findall(lowered))


def dice_coverage(candidate: str, gold: str) -> float:
    """Dice coefficient over token sets; 1.0 means identical token sets."""

    left = token_set(candidate)
    right = token_set(gold)
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return round(2.0 * overlap / (len(left) + len(right)), 4)


def source_precision(candidate: tuple[str, ...], actual: tuple[str, ...]) -> float:
    """Fraction of claimed sources that actually belong to the theme."""

    claimed = set(candidate)
    real = set(actual)
    if not claimed:
        return 0.0
    return round(len(claimed & real) / len(claimed), 4)


def source_recall(candidate: tuple[str, ...], actual: tuple[str, ...]) -> float:
    """Fraction of real sources that the summary managed to cite."""

    claimed = set(candidate)
    real = set(actual)
    if not real:
        return 1.0
    return round(len(claimed & real) / len(real), 4)


def kind_score(candidate: ThemeSummary, gold: ThemeSummary) -> float:
    """1.0 when kinds match, otherwise 0.0."""

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
    """Score one candidate summary against one human gold answer."""

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
