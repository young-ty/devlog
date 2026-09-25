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
    GENERATION_MODE_AI,
    GENERATION_MODE_OFFLINE,
    GENERATION_MODE_UNKNOWN,
    SECTION_ASSETS,
    SECTION_DECISIONS,
    SECTION_ISSUES,
    SECTION_LESSONS,
    SECTION_NEXT,
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    ClaimStatus,
    ReviewQuestion,
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
    def test_generation_mode_defaults_to_unknown_and_can_be_set(self) -> None:
        """没显式传模式时按 unknown 处理，避免假装跑过 AI 归纳。"""

        kwargs = dict(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1)],
            themes=[],
            theme_summaries=[],
            silence_periods=[],
        )
        self.assertEqual(
            build_review_draft(**kwargs).generation_mode,
            GENERATION_MODE_UNKNOWN,
        )
        self.assertEqual(
            build_review_draft(
                **kwargs, generation_mode=GENERATION_MODE_AI
            ).generation_mode,
            GENERATION_MODE_AI,
        )
        self.assertEqual(
            build_review_draft(
                **kwargs, generation_mode=GENERATION_MODE_OFFLINE
            ).generation_mode,
            GENERATION_MODE_OFFLINE,
        )

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
        self.assertIn("待补充的问题", text)
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

    def test_finalized_draft_says_so_in_the_header(self) -> None:
        """定稿前后导出的是同一份草稿，但文首状态必须跟着变。"""

        text = export_markdown(
            self._draft(), status="finalized", finalized_at=at(3)
        )
        self.assertIn("已定稿", text)
        self.assertIn("2026-09-03", text)
        self.assertNotIn("进行中", text)

    def test_write_markdown_forwards_finalize_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "final.md"
            written = write_markdown(
                self._draft(), target, status="finalized", finalized_at=at(3)
            )
            text = written.read_text(encoding="utf-8")
            self.assertIn("已定稿", text)

    def test_export_lists_every_section_in_a_toc_line(self) -> None:
        """文首目录行用图标引导，读的人一眼看到这份复盘覆盖了哪些板块。"""

        text = export_markdown(self._draft())
        toc = next(
            line for line in text.splitlines() if line.startswith("**目录**")
        )
        self.assertIn("**目录**", toc)
        self.assertIn("📄 项目概述", toc)
        self.assertIn("🔀 开发时间线", toc)

    def test_finalized_export_summarises_pending_instead_of_dumping_it(self) -> None:
        """定稿导出是拿去给别人看的成稿，不能把几十条 AI 猜测一起倒出来。"""

        draft = self._draft()
        pending = [
            claim.text
            for claim in draft.claims
            if claim.status is ClaimStatus.AI_PENDING
        ]
        self.assertTrue(pending, "样例草稿应当含有待确认的 AI 推断")

        draft_text = export_markdown(draft)
        self.assertIn(pending[0], draft_text)

        final_text = export_markdown(
            draft, status="finalized", finalized_at=at(3)
        )
        self.assertNotIn(pending[0], final_text)
        self.assertIn(f"共 {len(pending)} 条 AI 推断未通过确认", final_text)


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


class AnswerExportTests(unittest.TestCase):
    """用户填的回答要落回对应板块，而不是堆在文末。"""

    def _draft(self, answers: dict[int, str] | None = None):
        draft = build_review_draft(
            project_name="demo",
            range_start=at(1),
            range_end=at(2),
            events=[make_event(1, 1)],
            themes=[],
            theme_summaries=[],
            silence_periods=[],
        )
        merged = answers or {}
        draft.questions = [
            ReviewQuestion(
                text=question.text,
                section=question.section,
                answer=merged.get(number, ""),
            )
            for number, question in enumerate(draft.questions, start=1)
        ]
        return draft

    def test_answer_is_rendered_inside_its_section(self) -> None:
        text = export_markdown(self._draft({1: "选 SQLite 是因为要零部署。"}))
        decisions = text.split("## 技术决策记录")[1].split("##")[0]
        self.assertIn("✍️ 我的补充（第 1 问）", decisions)
        self.assertIn("选 SQLite 是因为要零部署。", decisions)
        self.assertNotIn("请回答文末第 1 个引导问题", decisions)

    def test_answered_question_drops_out_of_pending_list(self) -> None:
        text = export_markdown(self._draft({1: "已经写过了。"}))
        pending = text.split("## 待补充的问题（人机共创）")[1]
        self.assertNotIn("技术选型", pending)
        self.assertIn("2. ", pending)
        self.assertIn("3. ", pending)

    def test_all_answered_removes_pending_section(self) -> None:
        text = export_markdown(
            self._draft({1: "a", 2: "b", 3: "c"})
        )
        self.assertNotIn("待补充的问题", text)

    def test_multiline_answer_is_indented(self) -> None:
        text = export_markdown(self._draft({3: "第一行\n第二行"}))
        self.assertIn("- ✍️ 我的补充（第 3 问）：第一行\n  第二行", text)

    def test_blank_answer_is_treated_as_unanswered(self) -> None:
        text = export_markdown(self._draft({1: "   "}))
        self.assertIn("请回答文末第 1 个引导问题", text)

    def test_legacy_answer_without_section_is_kept(self) -> None:
        """老草稿的问题没有板块归属，回答也不能在导出时凭空消失。"""

        draft = self._draft()
        draft.questions = [
            ReviewQuestion(text="老问题：这段时间在忙什么？", answer="在赶秋招投递。"),
            ReviewQuestion(text="老问题二", answer=""),
        ]
        text = export_markdown(draft)
        # 老草稿没有 section 的回答统一收进「其他补充」，标题和界面上一致。
        self.assertIn("## 其他补充", text)
        self.assertNotIn("## 其他补充（人机共创）", text)
        self.assertIn("在赶秋招投递。", text)
        self.assertNotIn("老问题：这段时间在忙什么？", text.split("## 待补充的问题")[0])


if __name__ == "__main__":
    unittest.main()
