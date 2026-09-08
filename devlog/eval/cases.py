"""Human-annotated golden set for DevLog theme summary evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.themes import ThemeSummary
from devlog.core.theming.models import Theme


TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class EvalCase:
    name: str
    theme: Theme
    commits: list[CommitEvent] = field(default_factory=list)
    gold: ThemeSummary | None = None


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=TZ)


def _commit(sequence: int, day: int, subject: str, hour: int = 9) -> CommitEvent:
    return CommitEvent(
        hash=f"{sequence:040d}",
        short_hash=f"{sequence:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=_at(day, hour),
        message_subject=subject,
        files_changed=1,
        insertions=5,
        deletions=1,
        parents_count=0,
        noise_type=NoiseType.NONE,
    )


def _case(
    name: str,
    title: str,
    kind: str,
    rows: list[tuple[int, str]],
    summary: str,
    milestone: bool = False,
) -> EvalCase:
    events = [
        _commit(sequence, day, subject)
        for sequence, (day, subject) in enumerate(rows, start=1)
    ]
    hashes = tuple(event.hash for event in events)
    theme = Theme(
        id=f"theme-{name}",
        title=title,
        kind=kind,
        commit_hashes=hashes,
        started_at=events[0].committed_at,
        ended_at=events[-1].committed_at,
        commit_count=len(events),
        is_milestone_candidate=milestone,
    )
    gold = ThemeSummary(
        title=title,
        kind=kind,
        summary=summary,
        sources=hashes,
    )
    return EvalCase(name=name, theme=theme, commits=events, gold=gold)


def build_cases() -> list[EvalCase]:
    """Return the full golden set used by offline and online evaluation."""

    return [
        _case(
            name="login_feature",
            title="login",
            kind="feature",
            rows=[
                (1, "feat: add login page"),
                (1, "feat: add login api"),
                (2, "fix: login button"),
            ],
            summary="登录功能实现了页面、接口和按钮修复，共 3 次提交，类型为 feature。",
        ),
        _case(
            name="checkout_bugfix",
            title="checkout total",
            kind="bugfix",
            rows=[
                (2, "fix: checkout total calculation"),
                (2, "fix: checkout rounding precision"),
                (3, "test: checkout total"),
            ],
            summary="修复了结账金额计算与舍入精度问题并补充测试，共 3 次提交，类型为 bugfix。",
        ),
        _case(
            name="theme_split_refactor",
            title="theme service",
            kind="refactor",
            rows=[
                (3, "refactor: split theme service"),
                (4, "refactor: move theme models"),
                (4, "test: theme refactor split"),
            ],
            summary="重构拆分了主题服务与模型并补充回归测试，共 3 次提交，类型为 refactor。",
        ),
        _case(
            name="v1_release",
            title="release",
            kind="feature",
            rows=[
                (5, "feat: release v1.0"),
                (5, "docs: release notes v1.0"),
            ],
            summary="发布了 v1.0 并补充发布说明，是里程碑，共 2 次提交，类型为 feature。",
            milestone=True,
        ),
        _case(
            name="usage_docs",
            title="usage docs",
            kind="docs",
            rows=[
                (6, "docs: add usage guide"),
                (6, "docs: add architecture overview"),
            ],
            summary="补充了使用指南与架构说明文档，共 2 次提交，类型为 docs。",
        ),
        _case(
            name="scan_perf",
            title="git scan cache",
            kind="perf",
            rows=[
                (7, "perf: cache git log parse"),
                (7, "perf: reuse scan results"),
                (8, "fix: cache invalidation"),
            ],
            summary="优化了 Git 日志解析与扫描结果复用以提升性能，并修复缓存失效问题，共 3 次提交，类型为 perf。",
        ),
        _case(
            name="packaging_build",
            title="packaging",
            kind="build",
            rows=[
                (8, "build: add console script"),
                (8, "build: configure frontend build"),
            ],
            summary="完成了命令行打包并配置前端构建，共 2 次提交，类型为 build。",
        ),
        _case(
            name="web_frontend",
            title="web frontend",
            kind="feature",
            rows=[
                (9, "feat: add react web pages"),
                (9, "feat: add api proxy"),
                (9, "fix: web button"),
            ],
            summary="完成了网页前端与 API 代理并修复按钮问题，共 3 次提交，类型为 feature。",
        ),
    ]
