"""把草稿整理成一份"成稿"。

成稿和草稿只差一条规则：草稿里混着 AI 的推断，成稿只收人类认过的内容。

这条规则必须只有一份实现。界面要按它渲染，Markdown 导出迟早也要按它输出，
写两遍必然漂移——到时候你在界面上看到的和导出的文件不是一回事，那是最
难解释的一类 bug。所以规则放在这里，两个出口都从这儿拿。

注意本模块不依赖存储层：只吃一个纯 `ReviewDraft`。draft_id 之类的外部
上下文由调用方自己拼，这样连测试都不用碰数据库。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from devlog.core.review.models import (
    SECTION_ASSETS,
    SECTION_DECISIONS,
    SECTION_ISSUES,
    SECTION_LESSONS,
    SECTION_NEXT,
    SECTION_ORDER,
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
    ReviewQuestion,
)

# 只有这几种状态的论断才进成稿。ai_pending 是 AI 的猜测，还没经过用户
# 背书，混进正文就违反了"事实归事实、推断归推断"这个前提。
INCLUDED_STATUSES = frozenset(
    {ClaimStatus.FACT, ClaimStatus.CONFIRMED, ClaimStatus.EDITED}
)

# 章节图标名与前端 Icons 组件同名，前端只负责画，不负责猜。
SECTION_ICONS = {
    SECTION_OVERVIEW: "note",
    SECTION_TIMELINE: "commit",
    SECTION_DECISIONS: "tag",
    SECTION_ISSUES: "bug",
    SECTION_LESSONS: "warning",
    SECTION_ASSETS: "star",
    SECTION_NEXT: "help",
}

# 没有内容、也不会自动填充的章节，说明它的内容该从哪里来。
SECTION_HINTS = {
    SECTION_ISSUES: (
        "本板块由 Bug 捕获记录自动汇总。还没有内容时，"
        "用 Bug 捕获功能把报错、环境和 Git 状态存下来。"
    ),
    SECTION_ASSETS: "本板块由 AI 横跨所有开发主题归纳，逐条确认之后才算数。",
}

DEFAULT_SECTION_HINT = "本板块暂无可自动填充的内容。"


@dataclass(frozen=True)
class FinalClaim:
    """成稿里的一条陈述。`status` 用来给读者标出它是事实还是被改过。"""

    text: str
    status: str
    sources: tuple[str, ...] = ()
    user_note: str = ""

    @classmethod
    def from_claim(cls, claim: ReviewClaim) -> "FinalClaim":
        return cls(
            text=claim.text,
            status=claim.status.value,
            sources=tuple(claim.sources),
            user_note=claim.user_note,
        )


@dataclass(frozen=True)
class FinalAnswer:
    """用户针对某个章节写的补充，连带原问题一起带上。"""

    question_number: int
    question: str
    answer: str


@dataclass(frozen=True)
class FinalSection:
    """成稿的一章：正式内容 + 补充回答 + 这一章还欠着的问题。"""

    title: str
    icon: str
    claims: tuple[FinalClaim, ...] = ()
    answers: tuple[FinalAnswer, ...] = ()
    open_questions: tuple[str, ...] = ()
    hint: str = DEFAULT_SECTION_HINT

    @property
    def is_empty(self) -> bool:
        return not self.claims and not self.answers

    @property
    def count(self) -> int:
        """目录角标上的数字：正式内容加补充回答。"""

        return len(self.claims) + len(self.answers)


@dataclass(frozen=True)
class FinalDocument:
    """一份可以直接拿来读的复盘成稿。"""

    title: str
    project_name: str
    range_start: datetime
    range_end: datetime
    generated_at: datetime
    sections: tuple[FinalSection, ...]
    # 未通过确认的 AI 推断：不进正文，但要在界面上明确告诉用户有多少条。
    pending: tuple[FinalClaim, ...] = ()
    generation_mode: str = "unknown"

    @property
    def included_count(self) -> int:
        return sum(len(section.claims) for section in self.sections)

    @property
    def pending_count(self) -> int:
        return len(self.pending)


def section_placeholder(
    section: str,
    questions: list[ReviewQuestion] | tuple[ReviewQuestion, ...],
    *,
    where: str = "文末",
) -> str:
    """空章节的提示语：能指到具体问题就指过去，别只说"请回答下面的问题"。

    `where` 是问题清单所在的位置：Markdown 导出把它放在文末，界面把它放在
    独立章节，所以两边的措辞要跟着变，但"指到第几问"这个逻辑共用一份。
    """

    for index, question in enumerate(questions, start=1):
        if question.section == section:
            return f"本板块需要你补充：请回答{where}第 {index} 个引导问题。"
    return SECTION_HINTS.get(section, DEFAULT_SECTION_HINT)


def build_final_document(draft: ReviewDraft) -> FinalDocument:
    """按章节顺序组装成稿，把没确认的 AI 推断单独收起来。"""

    included: dict[str, list[FinalClaim]] = {name: [] for name in SECTION_ORDER}
    pending: list[FinalClaim] = []
    for claim in draft.claims:
        if claim.status in INCLUDED_STATUSES:
            # 老草稿可能带着已经不存在的章节名，归到「遗留与下一步」比丢掉好。
            bucket = included.setdefault(claim.section, [])
            bucket.append(FinalClaim.from_claim(claim))
        else:
            pending.append(FinalClaim.from_claim(claim))

    # 章节顺序固定：读过一次之后，下次打开文档结构不变，找东西不重新认路。
    ordered = list(SECTION_ORDER)
    for extra in included:
        if extra not in ordered:
            ordered.append(extra)

    sections: list[FinalSection] = []
    for section in ordered:
        answers = tuple(
            FinalAnswer(
                question_number=number,
                question=question.text,
                answer=question.answer.strip(),
            )
            for number, question in enumerate(draft.questions, start=1)
            if question.section == section and question.answer.strip()
        )
        open_questions = tuple(
            question.text
            for question in draft.questions
            if question.section == section and not question.answer.strip()
        )
        sections.append(
            FinalSection(
                title=section,
                icon=SECTION_ICONS.get(section, "note"),
                claims=tuple(included.get(section, ())),
                answers=answers,
                open_questions=open_questions,
                hint=section_placeholder(section, draft.questions, where="下面的"),
            )
        )

    return FinalDocument(
        title=f"{draft.project_name} · 开发复盘",
        project_name=draft.project_name,
        range_start=draft.range_start,
        range_end=draft.range_end,
        generated_at=draft.generated_at,
        sections=tuple(sections),
        pending=tuple(pending),
        generation_mode=draft.generation_mode,
    )
