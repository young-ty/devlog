"""把事件、主题和 AI 摘要组装成一份复盘草稿。"""

from __future__ import annotations

from datetime import datetime

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.themes import ThemeSummary
from devlog.core.review.models import (
    SECTION_ASSETS,
    SECTION_DECISIONS,
    SECTION_ISSUES,
    SECTION_LESSONS,
    SECTION_NEXT,
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
)
from devlog.core.theming.models import SilencePeriod, Theme


def _fmt(when: datetime) -> str:
    return when.strftime("%Y-%m-%d")


def build_review_draft(
    project_name: str,
    range_start: datetime,
    range_end: datetime,
    events: list[CommitEvent],
    themes: list[Theme],
    theme_summaries: list[ThemeSummary],
    silence_periods: list[SilencePeriod],
    factual_summaries: bool = False,
) -> ReviewDraft:
    """基于事实与 AI 摘要构建结构化草稿。

    AI 产生的内容一律标记为 ai_pending（待确认）。只有开发者本人
    才知道答案的板块（决策、踩坑、可复用资产、下一步）会生成引导
    问题，而不是编造陈述。

    factual_summaries=True 会把主题摘要标记为事实，用于离线 CLI
    模式——该模式下摘要是按规则从 commit 数据推导的，而不是由 LLM 生成。
    """

    if len(theme_summaries) != len(themes):
        raise ValueError("theme_summaries must be parallel to themes")

    meaningful = [event for event in events if event.noise_type == NoiseType.NONE]
    claims: list[ReviewClaim] = []
    questions: list[str] = []

    if not meaningful:
        return ReviewDraft(
            project_name=project_name,
            range_start=range_start,
            range_end=range_end,
            claims=claims,
            questions=questions,
        )

    sources = tuple(event.hash for event in meaningful)
    claims.append(
        ReviewClaim(
            section=SECTION_OVERVIEW,
            text=(
                f"在 {_fmt(range_start)} ~ {_fmt(range_end)} 期间，"
                f"共 {len(meaningful)} 次有效提交，"
                f"聚类为 {len(themes)} 个开发主题"
                + (f"，识别到 {len(silence_periods)} 段空档" if silence_periods else "")
                + "。"
            ),
            sources=sources,
            status=ClaimStatus.FACT,
        )
    )

    for theme, summary in zip(themes, theme_summaries):
        summary_sources = summary.sources or theme.commit_hashes
        claims.append(
            ReviewClaim(
                section=SECTION_TIMELINE,
                text=f"主题「{summary.title}」：{summary.summary}",
                sources=tuple(summary_sources),
                status=(
                    ClaimStatus.FACT
                    if factual_summaries
                    else ClaimStatus.AI_PENDING
                ),
            )
        )

    for period in silence_periods:
        questions.append(
            f"{_fmt(period.started_at)} 到 {_fmt(period.ended_at)} "
            f"之间有 {period.days} 天没有提交，这段时间发生了什么？"
        )

    questions.append(
        "这个项目里有哪些关键的技术选型决策？当时为什么这样选？"
        "（决策理由不在 Git 中，需要你补充）"
    )
    questions.append(
        "开发中遇到过哪些 Bug 或阻塞？是怎么定位和解决的？"
    )
    questions.append(
        "哪个决定最让你后悔？哪段代码重写时你会换一种做法？"
    )
    questions.append(
        "有没有值得沉淀为可复用资产的函数、模块或方案？"
    )
    questions.append(
        "项目还有哪些未完成事项？下一步计划是什么？"
    )

    return ReviewDraft(
        project_name=project_name,
        range_start=range_start,
        range_end=range_end,
        claims=claims,
        questions=questions,
    )
