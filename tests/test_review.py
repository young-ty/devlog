"""Module 5 tests: review draft engine and Markdown export."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.themes import ThemeSummary
from devlog.core.review.engine import build_review_draft
from devlog.core.review.markdown import ReviewExportError, export_markdown, write_markdown
from devlog.core.review.models import (
    SECTION_DECISIONS,
    SECTION_LESSONS,
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
        self.assertIn("没有提交", draft.questions[0])

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
            any("技术选型" in question for question in draft.questions)
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


if __name__ == "__main__":
    unittest.main()
