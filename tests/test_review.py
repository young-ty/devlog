"""模块 5 测试：复盘草稿引擎与 Markdown 导出。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devlog.core.capture.models import BugRecord, BugStatus
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.themes import AssetSummary, ThemeSummary
from devlog.core.review.engine import build_review_draft
from devlog.core.review.markdown import ReviewExportError, export_markdown, write_markdown
from devlog.core.review.models import (
    SECTION_ASSETS,
    SECTION_DECISIONS,
    SECTION_ISSUES,
    SECTION_LESSONS,
    SECTION_NEXT,
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    ClaimStatus,
)
from devlog.core.theming.models import SilencePeriod, Theme


TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=TZ)


def make_event(number: int, day: int) -> CommitEvent:
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


def sample_theme() -> Theme:
    return Theme(
        id="theme-1",
        title="login",
        kind="feature",
        commit_hashes=(f"{1:040d}", f"{2:040d}"),
        started_at=at(1),
        ended_at=at(2),
        commit_count=2,
    )


def sample_summary() -> ThemeSummary:
    return ThemeSummary(
        title="login",
        kind="feature",
        summary="围绕登录页面与接口实现功能，并修复按钮错位。",
        sources=(f"{1:040d}", f"{2:040d}"),
    )


class ReviewEngineTests(unittest.TestCase):
    def test_builds_full_draft(self) -> None:
        events = [make_event(1, 1), make_event(2, 2)]
        themes = [sample_theme()]
        summaries = [sample_summary()]
        silence = [SilencePeriod(started_at=at(2), ended_at=at(5), days=3)]

        draft = build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(5),
            events=events,
            themes=themes,
            theme_summaries=summaries,
            silence_periods=silence,
        )

        self.assertEqual(draft.claims[0].section, SECTION_OVERVIEW)
        self.assertEqual(draft.claims[0].status, ClaimStatus.FACT)
        self.assertEqual(draft.claims[1].section, SECTION_TIMELINE)
        self.assertEqual(draft.claims[1].status, ClaimStatus.AI_PENDING)
        self.assertIn("没有提交", draft.questions[0].text)

    def test_decision_and_lesson_sections_have_no_ai_claims(self) -> None:
        draft = build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1)],
            themes=[],
            theme_summaries=[],
            silence_periods=[],
        )

        sections = {claim.section for claim in draft.claims}
        self.assertNotIn(SECTION_DECISIONS, sections)
        self.assertNotIn(SECTION_LESSONS, sections)
        self.assertTrue(
            any("技术选型" in question.text for question in draft.questions)
        )

    def test_mismatched_theme_summaries_raise(self) -> None:
        with self.assertRaises(ValueError):
            build_review_draft(
                project_name="demo",
                range_start=at(1),
                range_end=at(2),
                events=[make_event(1, 1)],
                themes=[sample_theme()],
                theme_summaries=[],
                silence_periods=[],
            )

    def test_empty_project_returns_empty_draft(self) -> None:
        draft = build_review_draft(
            project_name="empty",
            range_start=at(1),
            range_end=at(2),
            events=[],
            themes=[],
            theme_summaries=[],
            silence_periods=[],
        )
        self.assertEqual(draft.claims, [])
        self.assertEqual(draft.questions, [])

    def test_factual_summaries_are_marked_as_facts(self) -> None:
        draft = build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1), make_event(2, 2)],
            themes=[sample_theme()],
            theme_summaries=[sample_summary()],
            silence_periods=[],
            factual_summaries=True,
        )

        timeline = [claim for claim in draft.claims if claim.section == SECTION_TIMELINE]
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0].status, ClaimStatus.FACT)


class MarkdownExportTests(unittest.TestCase):
    def _draft(self):
        return build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1), make_event(2, 2)],
            themes=[sample_theme()],
            theme_summaries=[sample_summary()],
            silence_periods=[],
        )

    def test_rendered_markdown_contains_sections_and_status(self) -> None:
        text = export_markdown(self._draft())
        self.assertIn("# 复盘：demo", text)
        self.assertIn("## 项目概述", text)
        self.assertIn("## 开发时间线", text)
        self.assertIn("AI 推断", text)
        self.assertIn("待回答的问题", text)
        self.assertIn("来源：`" + f"{1:040d}" + "`", text)

    def test_write_creates_parent_directories(self) -> None:
        draft = self._draft()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "review.md"
            written = write_markdown(draft, target)
            self.assertTrue(written.exists())
            self.assertEqual(written.read_text(encoding="utf-8"), export_markdown(draft))

    def test_write_rejects_directory_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ReviewExportError):
                write_markdown(self._draft(), Path(tmp))


class GuidanceQuestionTests(unittest.TestCase):
    """引导问题要精简、要落到具体板块，且不再问已经能自动拿到的东西。"""

    def build(self, **overrides):
        payload = dict(
            project_name="demo",
            range_start=at(1),
            range_end=at(3),
            events=[make_event(1, 1), make_event(2, 2)],
            themes=[sample_theme()],
            theme_summaries=[sample_summary()],
            silence_periods=[],
        )
        payload.update(overrides)
        return build_review_draft(**payload)

    def test_questions_are_few_and_map_to_sections(self) -> None:
        draft = self.build()
        self.assertEqual(len(draft.questions), 3)
        self.assertEqual(
            [question.section for question in draft.questions],
            [SECTION_DECISIONS, SECTION_LESSONS, SECTION_NEXT],
        )

    def test_bug_question_is_gone(self) -> None:
        """Bug 已经有捕获功能，不该再反问用户一遍。"""

        draft = self.build()
        joined = "".join(question.text for question in draft.questions)
        self.assertNotIn("Bug", joined)

    def test_silence_question_keeps_timeline_section(self) -> None:
        draft = self.build(
            silence_periods=[SilencePeriod(started_at=at(2), ended_at=at(5), days=3)]
        )
        self.assertEqual(draft.questions[0].section, SECTION_TIMELINE)
        self.assertIn("没有提交", draft.questions[0].text)

    def test_bug_records_fill_issues_section_as_facts(self) -> None:
        bug = BugRecord(
            title="SSE 流式响应被缓冲",
            error_text="Traceback ...",
            git_head=f"{1:040d}",
            status=BugStatus.RESOLVED,
            root_cause="中间件设置了 buffering",
            solution="关掉 buffering 并逐条 flush",
        )
        draft = self.build(bug_records=[bug])

        issues = [
            claim for claim in draft.claims if claim.section == SECTION_ISSUES
        ]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].status, ClaimStatus.FACT)
        self.assertIn("SSE 流式响应被缓冲", issues[0].text)
        self.assertIn("已解决", issues[0].text)
        self.assertIn("逐条 flush", issues[0].text)
        self.assertEqual(issues[0].sources, (f"{1:040d}",))

    def test_open_bug_without_solution_still_recorded(self) -> None:
        draft = self.build(bug_records=[BugRecord(title="还没定位的问题")])
        issues = [
            claim for claim in draft.claims if claim.section == SECTION_ISSUES
        ]
        self.assertEqual(len(issues), 1)
        self.assertIn("待定位根因", issues[0].text)
        self.assertEqual(issues[0].sources, ())

    def test_asset_summaries_become_pending_claims(self) -> None:
        asset = AssetSummary(
            name="Git 扫描模块",
            rationale="扫描与解析逻辑可以复用到其他仓库分析工具。",
            sources=(f"{1:040d}",),
        )
        draft = self.build(asset_summaries=[asset])

        assets = [
            claim for claim in draft.claims if claim.section == SECTION_ASSETS
        ]
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].status, ClaimStatus.AI_PENDING)
        self.assertIn("Git 扫描模块", assets[0].text)
        self.assertEqual(assets[0].sources, (f"{1:040d}",))

    def test_no_assets_means_no_asset_claims(self) -> None:
        draft = self.build()
        self.assertFalse(
            [claim for claim in draft.claims if claim.section == SECTION_ASSETS]
        )


class SectionPlaceholderTests(unittest.TestCase):
    def test_empty_human_section_points_at_its_question_number(self) -> None:
        draft = build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1)],
            themes=[],
            theme_summaries=[],
            silence_periods=[],
        )
        text = export_markdown(draft)
        self.assertIn("请回答文末第 1 个引导问题", text)
        self.assertIn("请回答文末第 2 个引导问题", text)
        self.assertIn("请回答文末第 3 个引导问题", text)

    def test_issues_section_points_at_bug_capture_not_a_question(self) -> None:
        draft = build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1)],
            themes=[],
            theme_summaries=[],
            silence_periods=[],
        )
        issues_block = export_markdown(draft).split("## 问题与解决")[1]
        self.assertIn("Bug 捕获", issues_block.split("##")[0])


if __name__ == "__main__":
    unittest.main()
