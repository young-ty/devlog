"""Module 9 tests: golden-set eval metrics, offline baseline and online judge.

Rule summaries are deterministic and offline scoring never calls a real API.
The online judge path is covered with a FakeClient so the suite stays free,
fast and deterministic.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.themes import ThemeSummary, rule_based_summary
from devlog.core.theming.models import Theme
from devlog.eval.cases import EvalCase, build_cases
from devlog.eval.metrics import (
    dice_coverage,
    evaluate_summary,
    kind_score,
    source_precision,
    source_recall,
    token_set,
)
from devlog.eval.runner import llm_judge, run_cli, run_offline, run_online


TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=TZ)


def make_commit(number: int, day: int) -> CommitEvent:
    return CommitEvent(
        hash=f"{number:040d}",
        short_hash=f"{number:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=at(day),
        message_subject="feat: add login page",
        files_changed=1,
        insertions=1,
        deletions=0,
        parents_count=0,
        noise_type=NoiseType.NONE,
    )


def make_theme(
    kind: str = "feature",
    commit_numbers: tuple[int, ...] = (1, 2),
) -> Theme:
    hashes = tuple(f"{number:040d}" for number in commit_numbers)
    return Theme(
        id="theme-login",
        title="login",
        kind=kind,
        commit_hashes=hashes,
        started_at=at(1),
        ended_at=at(2),
        commit_count=len(hashes),
    )


def make_summary(
    text: str,
    kind: str = "feature",
    sources: tuple[str, ...] = (f"{1:040d}", f"{2:040d}"),
) -> ThemeSummary:
    return ThemeSummary(title="login", kind=kind, summary=text, sources=sources)


class TokenAndCoverageTests(unittest.TestCase):
    def test_token_set_mixes_cjk_and_latin(self) -> None:
        tokens = token_set("DevLog 登录 logout Feature feature")

        self.assertIn("devlog", tokens)
        self.assertIn("logout", tokens)
        self.assertIn("feature", tokens)
        self.assertIn("登", tokens)
        self.assertIn("录", tokens)

    def test_token_set_ignores_punctuation(self) -> None:
        self.assertEqual(token_set("，。！（）()：:\t\n"), set())

    def test_dice_identical_text_is_one(self) -> None:
        self.assertEqual(dice_coverage("登录功能 feature", "功能登录feature"), 1.0)

    def test_dice_disjoint_text_is_zero(self) -> None:
        self.assertEqual(dice_coverage("登录功能", "支付结算"), 0.0)

    def test_dice_empty_side_is_zero(self) -> None:
        self.assertEqual(dice_coverage("", "登录"), 0.0)
        self.assertEqual(dice_coverage("登录", ""), 0.0)

    def test_semantic_paraphrase_is_undervalued_by_lexical_match(self) -> None:
        # Same meaning, but no shared characters -> lexical coverage cannot see it.
        self.assertEqual(dice_coverage("身份认证工作结束", "登录功能完成"), 0.0)


class SourceMetricTests(unittest.TestCase):
    def test_precision_and_recall_are_perfect_for_exact_sources(self) -> None:
        sources = (f"{1:040d}", f"{2:040d}")
        self.assertEqual(source_precision(sources, sources), 1.0)
        self.assertEqual(source_recall(sources, sources), 1.0)

    def test_fabricated_source_lowers_precision(self) -> None:
        real = (f"{1:040d}", f"{2:040d}")
        claimed = real + (f"{999:040d}",)
        self.assertAlmostEqual(source_precision(claimed, real), 0.6667, places=4)
        self.assertEqual(source_recall(claimed, real), 1.0)

    def test_missing_real_source_lowers_recall(self) -> None:
        real = (f"{1:040d}", f"{2:040d}")
        claimed = real[:1]
        self.assertEqual(source_precision(claimed, real), 1.0)
        self.assertAlmostEqual(source_recall(claimed, real), 0.5)

    def test_no_claimed_sources_score_zero_precision(self) -> None:
        self.assertEqual(source_precision((), (f"{1:040d}",)), 0.0)

    def test_empty_real_sources_score_full_recall(self) -> None:
        self.assertEqual(source_recall((f"{1:040d}",), ()), 1.0)


class KindAndOverallTests(unittest.TestCase):
    def test_kind_match_is_case_and_space_insensitive(self) -> None:
        candidate = make_summary("text", kind=" feature ")
        gold = make_summary("text", kind="FEATURE")
        self.assertEqual(kind_score(candidate, gold), 1.0)

    def test_kind_mismatch_scores_zero(self) -> None:
        candidate = make_summary("text", kind="feature")
        gold = make_summary("text", kind="docs")
        self.assertEqual(kind_score(candidate, gold), 0.0)

    def test_perfect_summary_scores_one(self) -> None:
        candidate = make_summary("登录功能完成")
        gold = make_summary("登录功能完成")

        metrics = evaluate_summary(candidate, gold)
        self.assertEqual(metrics.coverage, 1.0)
        self.assertEqual(metrics.source_precision, 1.0)
        self.assertEqual(metrics.source_recall, 1.0)
        self.assertEqual(metrics.kind_score, 1.0)
        self.assertEqual(metrics.overall, 1.0)

    def test_half_coverage_applies_half_of_its_weight(self) -> None:
        gold = make_summary("alpha beta")
        candidate = make_summary("alpha gamma")

        metrics = evaluate_summary(candidate, gold)
        self.assertEqual(metrics.coverage, 0.5)
        self.assertEqual(metrics.source_precision, 1.0)
        self.assertEqual(metrics.source_recall, 1.0)
        self.assertEqual(metrics.kind_score, 1.0)
        self.assertAlmostEqual(metrics.overall, 0.5 * 0.5 + 0.15 + 0.15 + 0.2)

    def test_empty_and_fabricated_summary_scores_zero(self) -> None:
        gold = make_summary("登录", sources=(f"{1:040d}",))
        candidate = make_summary("", kind="other", sources=(f"{999:040d}",))

        metrics = evaluate_summary(candidate, gold)
        self.assertEqual(metrics.overall, 0.0)


class RuleBaselineTests(unittest.TestCase):
    def test_rule_based_summary_reuses_theme_facts(self) -> None:
        theme = make_theme(kind="bugfix")
        result = rule_based_summary(theme)

        self.assertEqual(result.kind, "bugfix")
        self.assertEqual(result.sources, theme.commit_hashes)
        self.assertIn("共 2 次提交", result.summary)
        self.assertIn("2026-09-01", result.summary)
        self.assertIn("2026-09-02", result.summary)
        self.assertIn("bugfix", result.summary)

    def test_offline_report_covers_eight_golden_cases(self) -> None:
        report = run_offline(build_cases(), threshold=0.0)

        self.assertEqual(len(report.results), 8)
        self.assertTrue(report.passed)
        self.assertTrue(all(item.judge_score is None for item in report.results))

    def test_threshold_controls_pass_fail(self) -> None:
        theme = make_theme()
        gold = rule_based_summary(theme)
        case = EvalCase(
            name="identical",
            theme=theme,
            commits=[make_commit(1, 1), make_commit(2, 2)],
            gold=gold,
        )

        self.assertTrue(run_offline([case], threshold=0.9999).passed)
        self.assertFalse(run_offline([case], threshold=1.0001).passed)


class FakeJudgeClient(LLMClientBase):
    def __init__(self, answer: ThemeSummary) -> None:
        self.answer = answer
        self.json_prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        return ""

    def complete_json(self, prompt: str) -> dict[str, Any]:
        self.json_prompts.append(prompt)
        return {
            "title": self.answer.title,
            "kind": self.answer.kind,
            "summary": self.answer.summary,
            "sources": list(self.answer.sources),
            "score": "5",
        }


class FixedScoreClient(LLMClientBase):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def complete(self, prompt: str) -> str:
        return ""

    def complete_json(self, prompt: str) -> dict[str, Any]:
        return dict(self.payload)


class OnlineJudgeTests(unittest.TestCase):
    def _case(self) -> EvalCase:
        theme = make_theme()
        return EvalCase(
            name="online-identical",
            theme=theme,
            commits=[make_commit(1, 1), make_commit(2, 2)],
            gold=rule_based_summary(theme),
        )

    def test_run_online_uses_generate_and_judge_calls(self) -> None:
        case = self._case()
        client = FakeJudgeClient(case.gold)

        report = run_online([case], client, threshold=0.0)

        self.assertEqual(len(client.json_prompts), 2)
        self.assertIn("候选摘要", client.json_prompts[1])
        self.assertEqual(report.results[0].judge_score, 5.0)
        self.assertEqual(report.results[0].metrics.overall, 1.0)
        self.assertTrue(report.passed)

    def test_judge_score_is_clamped_to_one_to_five(self) -> None:
        gold = make_summary("登录功能完成")
        candidate = make_summary("登录功能完成")

        high = llm_judge(FixedScoreClient({"score": "9"}), candidate, gold)
        low = llm_judge(FixedScoreClient({"score": "-2"}), candidate, gold)
        self.assertEqual(high, 5)
        self.assertEqual(low, 1)

    def test_judge_invalid_score_raises(self) -> None:
        gold = make_summary("登录功能完成")
        candidate = make_summary("登录功能完成")
        with self.assertRaises(LLMError):
            llm_judge(FixedScoreClient({"reason": "no score"}), candidate, gold)


class OfflineCliTests(unittest.TestCase):
    def test_run_cli_offline_passes_when_threshold_is_zero(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = run_cli(["--threshold", "0.0"])
        self.assertEqual(code, 0)

    def test_run_cli_offline_fails_when_threshold_is_unreachable(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = run_cli(["--threshold", "99.0"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
