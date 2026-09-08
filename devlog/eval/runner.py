"""Run the golden-set evaluation and summarize per-case metrics."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.deepseek import DeepSeekClient
from devlog.core.llm.themes import (
    ThemeSummary,
    complete_json_with_retry,
    rule_based_summary,
    summarize_theme,
)
from devlog.eval.cases import EvalCase, build_cases
from devlog.eval.metrics import SummaryMetrics, evaluate_summary


DEFAULT_THRESHOLD = 0.40

_JUDGE_INSTRUCTION = (
    "你是严格的复盘摘要评审。请只输出 JSON 对象，包含 "
    '"score"（1 到 5 的整数）和 "reason"（一句话中文理由）。'
)


@dataclass(frozen=True)
class CaseResult:
    name: str
    metrics: SummaryMetrics
    judge_score: float | None = None


@dataclass(frozen=True)
class EvalReport:
    results: list[CaseResult]
    threshold: float
    passed: bool

    def average(self, field: str) -> float:
        values = [getattr(item.metrics, field) for item in self.results]
        if not values:
            return 0.0
        return round(sum(values) / len(values), 4)


def _candidate_case(
    case: EvalCase,
    candidate: ThemeSummary,
    judge_score: float | None = None,
) -> CaseResult:
    if case.gold is None:
        raise ValueError(f"eval case has no gold answer: {case.name}")
    return CaseResult(
        name=case.name,
        metrics=evaluate_summary(candidate, case.gold),
        judge_score=judge_score,
    )


def run_offline(
    cases: list[EvalCase],
    threshold: float = DEFAULT_THRESHOLD,
) -> EvalReport:
    """Score the deterministic rule-based baseline (no API calls)."""

    results = [
        _candidate_case(case, rule_based_summary(case.theme))
        for case in cases
    ]
    return _finish(results, threshold=threshold)


def llm_judge(
    client: LLMClientBase,
    candidate: ThemeSummary,
    gold: ThemeSummary,
) -> int:
    """Ask a second model to score candidate quality from 1 to 5."""

    prompt = (
        "候选摘要：\n"
        f"{candidate.summary}\n\n"
        "人工标准答案：\n"
        f"{gold.summary}\n\n"
        "根据内容相关性、完整性、幻觉程度打分。\n"
        + _JUDGE_INSTRUCTION
    )
    data = complete_json_with_retry(client, prompt)
    try:
        score = int(data["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMError("LLM judge returned no valid score") from exc
    return max(1, min(5, score))


def run_online(
    cases: list[EvalCase],
    client: LLMClientBase,
    threshold: float = DEFAULT_THRESHOLD,
) -> EvalReport:
    """Generate candidates with DeepSeek and judge them with another call."""

    results: list[CaseResult] = []
    for case in cases:
        candidate = summarize_theme(case.theme, case.commits, client)
        if case.gold is None:
            raise ValueError(f"eval case has no gold answer: {case.name}")
        judge = llm_judge(client, candidate, case.gold)
        results.append(_candidate_case(case, candidate, judge_score=float(judge)))
    return _finish(results, threshold=threshold)


def _finish(results: list[CaseResult], threshold: float = DEFAULT_THRESHOLD) -> EvalReport:
    values = [item.metrics.overall for item in results]
    average = sum(values) / len(values) if values else 0.0
    return EvalReport(
        results=results,
        threshold=threshold,
        passed=average >= threshold,
    )


def _print_report(report: EvalReport) -> None:
    print("用例              覆盖度  精确率  召回率  类型  总分  LLM")
    for item in report.results:
        metrics = item.metrics
        judge = f"{item.judge_score:.1f}" if item.judge_score is not None else "-"
        print(
            f"{item.name:<18}"
            f"{metrics.coverage:<7.2f}"
            f"{metrics.source_precision:<7.2f}"
            f"{metrics.source_recall:<7.2f}"
            f"{metrics.kind_score:<5.0f}"
            f"{metrics.overall:<6.2f}"
            f"{judge}"
        )

    average = report.average("overall")
    print("-" * 58)
    print(f"平均总分：{average:.2f}（阈值 {report.threshold:.2f}）")
    if report.passed:
        print("通过：质量在阈值之上。")
    else:
        print("失败：质量低于阈值，请检查最近改动。")


def run_cli(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m devlog.eval``."""

    parser = argparse.ArgumentParser(
        prog="devlog-eval",
        description="用人工 golden set 评估主题摘要质量。",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="调用 DeepSeek 生成摘要并启用 LLM-as-judge（需要 API key）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"平均总分阈值（默认 {DEFAULT_THRESHOLD}）",
    )
    args = parser.parse_args(argv)

    try:
        cases = build_cases()
        if args.online:
            client = DeepSeekClient()
            report = run_online(cases, client, threshold=args.threshold)
        else:
            report = run_offline(cases, threshold=args.threshold)
    except LLMError as exc:
        print(f"评测失败：{exc}", file=sys.stderr)
        return 1

    _print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
