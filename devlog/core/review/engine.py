"""把事件、主题和 AI 摘要组装成一份复盘草稿。"""

from __future__ import annotations

from datetime import datetime

from devlog.core.capture.models import BugRecord, BugStatus
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.themes import AssetSummary, ThemeSummary
from devlog.core.review.models import (
    GENERATION_MODE_UNKNOWN,
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
    ReviewQuestion,
)
from devlog.core.theming.models import SilencePeriod, Theme


BUG_STATUS_LABELS = {
    BugStatus.OPEN: "待定位根因",
    BugStatus.ROOT_CAUSE_FOUND: "已找到根因",
    BugStatus.RESOLVED: "已解决",
}


# 需要开发者本人回答的问题，一条对应一个 Git 里查不到的板块。
# 刻意保持精简：问题越多，用户越容易跳过整段。
# 不在这里问 Bug —— 那是 Bug 捕获功能的活，答案直接从记录里来。
BASE_QUESTIONS: tuple[ReviewQuestion, ...] = (
    ReviewQuestion(
        section=SECTION_DECISIONS,
        text=(
            "这个项目里有哪些关键的技术选型或方案决策？当时为什么这样选？"
            "现在回头看，有哪个决定你会改变？"
        ),
    ),
    ReviewQuestion(
        section=SECTION_LESSONS,
        text=(
            "踩过的坑里，哪一个最值得记在自己本子上？"
            "根因是什么，下次怎么避免？"
        ),
    ),
    ReviewQuestion(
        section=SECTION_NEXT,
        text="项目还有哪些未完成事项？接下来打算怎么做？",
    ),
)


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
    bug_records: list[BugRecord] | None = None,
    asset_summaries: list[AssetSummary] | None = None,
    generation_mode: str = GENERATION_MODE_UNKNOWN,
) -> ReviewDraft:
    """基于事实与 AI 摘要构建结构化草稿。

    AI 产生的内容一律标记为 ai_pending（待确认）。只有开发者本人
    才知道答案的板块（决策、踩坑、下一步）会生成引导问题，
    而不是编造陈述。

    Bug 记录与可复用资产不再靠提问获取：
    - Bug 记录是用户已经捕获过的事实，直接汇总进「问题与解决」板块；
    - 可复用资产由 AI 横跨所有主题归纳，作为待确认论断给出。

    factual_summaries=True 会把主题摘要标记为事实，用于离线 CLI
    模式——该模式下摘要是按规则从 commit 数据推导的，而不是由 LLM 生成。
    """

    if len(theme_summaries) != len(themes):
        raise ValueError("theme_summaries must be parallel to themes")

    meaningful = [event for event in events if event.noise_type == NoiseType.NONE]
    claims: list[ReviewClaim] = []
    questions: list[ReviewQuestion] = []

    if not meaningful:
        return ReviewDraft(
            project_name=project_name,
            range_start=range_start,
            range_end=range_end,
            claims=claims,
            questions=questions,
            generation_mode=generation_mode,
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
            ReviewQuestion(
                section=SECTION_TIMELINE,
                text=(
                    f"{_fmt(period.started_at)} 到 {_fmt(period.ended_at)} "
                    f"之间有 {period.days} 天没有提交，这段时间发生了什么？"
                ),
            )
        )

    # Bug 记录已经是用户亲手捕获的事实，直接落进「问题与解决」，
    # 不再反过来问用户一遍。这里不按 --since/--until 过滤：
    # 草稿范围取的是首末提交时间，late 捕获的 Bug 会被错误地排除掉。
    for bug in bug_records or []:
        text = f"Bug「{bug.title}」：{BUG_STATUS_LABELS.get(bug.status, bug.status.value)}"
        detail = bug.solution or bug.root_cause
        if detail:
            text += f" —— {detail}"
        claims.append(
            ReviewClaim(
                section=SECTION_ISSUES,
                text=text + "。",
                sources=(bug.git_head,) if bug.git_head else (),
                status=ClaimStatus.FACT,
            )
        )

    for asset in asset_summaries or []:
        claims.append(
            ReviewClaim(
                section=SECTION_ASSETS,
                text=f"可复用资产候选「{asset.name}」：{asset.rationale}",
                sources=asset.sources,
                status=ClaimStatus.AI_PENDING,
            )
        )

    questions.extend(BASE_QUESTIONS)

    return ReviewDraft(
        project_name=project_name,
        range_start=range_start,
        range_end=range_end,
        claims=claims,
        questions=questions,
        generation_mode=generation_mode,
    )
