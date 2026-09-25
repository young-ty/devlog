"""成稿文档：只收人类认过的内容，并且和草稿共用同一套章节规则。"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from devlog.core.review.document import (
    INCLUDED_STATUSES,
    SECTION_ICONS,
    build_final_document,
)
from devlog.core.review.models import (
    GENERATION_MODE_AI,
    SECTION_ASSETS,
    SECTION_ISSUES,
    SECTION_ORDER,
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
    ReviewQuestion,
)


TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=TZ)


def make_draft(
    claims: list[ReviewClaim] | None = None,
    questions: list[ReviewQuestion] | None = None,
) -> ReviewDraft:
    return ReviewDraft(
        project_name="智能推荐菜谱",
        range_start=at(1),
        range_end=at(25),
        claims=claims or [],
        questions=questions or [],
        generated_at=at(25, 18),
        generation_mode=GENERATION_MODE_AI,
    )


class InclusionTests(unittest.TestCase):
    """成稿与草稿的唯一区别：AI 推断没被确认就不许进正文。"""

    def test_ai_pending_claims_stay_out_of_the_body(self) -> None:
        draft = make_draft(
            claims=[
                ReviewClaim(
                    section=SECTION_ORDER[0],
                    text="一共 96 个提交",
                    status=ClaimStatus.FACT,
                ),
                ReviewClaim(
                    section=SECTION_ORDER[0],
                    text="瓶颈在图片预处理",
                    status=ClaimStatus.AI_PENDING,
                ),
            ]
        )
        document = build_final_document(draft)

        body_texts = [
            claim.text
            for section in document.sections
            for claim in section.claims
        ]
        self.assertEqual(body_texts, ["一共 96 个提交"])
        self.assertEqual([claim.text for claim in document.pending], ["瓶颈在图片预处理"])
        self.assertEqual(document.included_count, 1)
        self.assertEqual(document.pending_count, 1)

    def test_confirmed_and_edited_claims_are_included(self) -> None:
        for status in (ClaimStatus.FACT, ClaimStatus.CONFIRMED, ClaimStatus.EDITED):
            with self.subTest(status=status):
                self.assertIn(status, INCLUDED_STATUSES)
                document = build_final_document(
                    make_draft(
                        claims=[
                            ReviewClaim(
                                section=SECTION_ORDER[0],
                                text="一句话",
                                status=status,
                            )
                        ]
                    )
                )
                self.assertEqual(document.included_count, 1)
                self.assertEqual(document.pending_count, 0)

    def test_claim_metadata_survives_the_conversion(self) -> None:
        draft = make_draft(
            claims=[
                ReviewClaim(
                    section=SECTION_ORDER[2],
                    text="推荐先走规则兜底",
                    sources=("来自 4 个提交",),
                    status=ClaimStatus.EDITED,
                    user_note="我自己改过措辞",
                )
            ]
        )
        claim = build_final_document(draft).sections[2].claims[0]
        self.assertEqual(claim.status, "edited")
        self.assertEqual(claim.sources, ("来自 4 个提交",))
        self.assertEqual(claim.user_note, "我自己改过措辞")


class SectionTests(unittest.TestCase):
    """章节顺序固定，读过一次之后结构就不该再变。"""

    def test_sections_follow_the_declared_order(self) -> None:
        document = build_final_document(make_draft())
        self.assertEqual(
            [section.title for section in document.sections],
            list(SECTION_ORDER),
        )

    def test_every_section_has_an_icon(self) -> None:
        document = build_final_document(make_draft())
        for section in document.sections:
            with self.subTest(section=section.title):
                self.assertTrue(section.icon)
                self.assertEqual(section.icon, SECTION_ICONS[section.title])

    def test_unknown_section_is_appended_not_dropped(self) -> None:
        """老草稿可能带着已经不用的章节名，内容不能凭空消失。"""

        draft = make_draft(
            claims=[
                ReviewClaim(
                    section="旧版遗留章节",
                    text="这句不能丢",
                    status=ClaimStatus.FACT,
                )
            ]
        )
        document = build_final_document(draft)
        titles = [section.title for section in document.sections]
        self.assertEqual(titles[: len(SECTION_ORDER)], list(SECTION_ORDER))
        self.assertIn("旧版遗留章节", titles)
        self.assertEqual(document.included_count, 1)

    def test_empty_section_points_at_its_question(self) -> None:
        draft = make_draft(
            questions=[
                ReviewQuestion(text="这段时间在忙什么？", section=SECTION_ORDER[1])
            ]
        )
        section = build_final_document(draft).sections[1]
        self.assertTrue(section.is_empty)
        self.assertIn("第 1 个引导问题", section.hint)
        self.assertEqual(section.open_questions, ("这段时间在忙什么？",))

    def test_issues_section_points_at_bug_capture(self) -> None:
        section = build_final_document(make_draft()).sections[
            SECTION_ORDER.index(SECTION_ISSUES)
        ]
        self.assertIn("Bug 捕获", section.hint)

    def test_assets_section_waits_for_confirmation(self) -> None:
        section = build_final_document(make_draft()).sections[
            SECTION_ORDER.index(SECTION_ASSETS)
        ]
        self.assertIn("逐条确认", section.hint)


class AnswerTests(unittest.TestCase):
    """你写的补充要落回它所属的那一章，而不是堆在文末。"""

    def test_answered_question_lands_in_its_section(self) -> None:
        draft = make_draft(
            questions=[
                ReviewQuestion(
                    text="哪个决策是你自己拍的板？",
                    section=SECTION_ORDER[2],
                    answer="范围收敛是我拍的板",
                )
            ]
        )
        section = build_final_document(draft).sections[2]
        self.assertEqual(len(section.answers), 1)
        self.assertEqual(section.answers[0].question_number, 1)
        self.assertEqual(section.answers[0].answer, "范围收敛是我拍的板")
        self.assertEqual(section.open_questions, ())

    def test_blank_answer_counts_as_open(self) -> None:
        draft = make_draft(
            questions=[
                ReviewQuestion(
                    text="如果重做一次会改哪一步？",
                    section=SECTION_ORDER[2],
                    answer="   ",
                )
            ]
        )
        section = build_final_document(draft).sections[2]
        self.assertEqual(section.answers, ())
        self.assertEqual(section.open_questions, ("如果重做一次会改哪一步？",))

    def test_section_count_includes_answers_and_claims(self) -> None:
        draft = make_draft(
            claims=[
                ReviewClaim(
                    section=SECTION_ORDER[2],
                    text="一句事实",
                    status=ClaimStatus.FACT,
                )
            ],
            questions=[
                ReviewQuestion(text="问题", section=SECTION_ORDER[2], answer="答案")
            ],
        )
        self.assertEqual(build_final_document(draft).sections[2].count, 2)


class DocumentHeaderTests(unittest.TestCase):
    def test_title_and_range_come_from_the_draft(self) -> None:
        document = build_final_document(make_draft())
        self.assertEqual(document.title, "智能推荐菜谱 · 开发复盘")
        self.assertEqual(document.project_name, "智能推荐菜谱")
        self.assertEqual(document.range_start, at(1))
        self.assertEqual(document.range_end, at(25))
        self.assertEqual(document.generation_mode, GENERATION_MODE_AI)

    def test_empty_draft_produces_a_readable_document(self) -> None:
        document = build_final_document(make_draft())
        self.assertEqual(document.included_count, 0)
        self.assertEqual(document.pending_count, 0)
        self.assertTrue(all(section.is_empty for section in document.sections))


if __name__ == "__main__":
    unittest.main()
