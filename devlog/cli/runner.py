"""Business orchestration shared by the CLI and, later, the local API.

These functions know nothing about argparse: they receive a database and
paths/options and return plain result objects. main.py only translates
terminal input into calls here and prints the results back.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from devlog.core.git_source.scanner import GitSourceError, scan_repository
from devlog.core.llm.deepseek import DeepSeekClient
from devlog.core.llm.themes import ThemeSummary, summarize_theme
from devlog.core.review.engine import build_review_draft
from devlog.core.review.markdown import write_markdown
from devlog.core.review.models import ClaimStatus
from devlog.core.storage.database import (
    DevLogDB,
    ReviewDraftSummary,
    StoredReviewDraft,
)
from devlog.core.theming.cluster import cluster_themes
from devlog.core.theming.models import Theme


class CLIUsageError(ValueError):
    """Raised when the requested action cannot be performed."""


@dataclass(frozen=True)
class InitResult:
    project_id: int
    project_name: str
    project_path: str


@dataclass(frozen=True)
class ScanResult:
    project_id: int
    project_name: str
    project_path: str
    total_events: int
    inserted_events: int
    reset: bool


@dataclass(frozen=True)
class GenerateResult:
    draft_id: int
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    claim_count: int
    ai_pending_count: int
    question_count: int
    offline: bool


@dataclass(frozen=True)
class ConfirmResult:
    draft_id: int
    changed: int
    remaining_pending: int


def _resolve(path: str | Path | None) -> Path:
    raw = Path(path) if path is not None else Path.cwd()
    return raw.expanduser().resolve()


def _assert_git_repo(repo: Path) -> None:
    """Raise a friendly error when a path is not a Git working tree."""

    if not repo.is_dir():
        raise CLIUsageError(f"路径不存在或不是目录：{repo}")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise CLIUsageError("未找到 git 可执行文件，请先安装 Git") from exc
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise CLIUsageError(f"不是 Git 仓库：{repo}（请先执行 git init）")


def cmd_init(
    db: DevLogDB,
    path: str | Path | None,
    name: str | None = None,
) -> InitResult:
    """Register a repository; registering the same path twice is a no-op."""

    repo = _resolve(path)
    _assert_git_repo(repo)
    project_name = name or repo.name or "project"
    project_id = db.register_project(project_name, repo)
    return InitResult(
        project_id=project_id,
        project_name=project_name,
        project_path=str(repo),
    )


def cmd_scan(
    db: DevLogDB,
    path: str | Path | None,
    reset: bool = False,
) -> ScanResult:
    """Scan the full Git history into the cache database."""

    repo = _resolve(path)
    _assert_git_repo(repo)
    name = repo.name or "project"
    project_id = db.register_project(name, repo)
    project_name = db.get_project(project_id).name

    events = scan_repository(repo)
    if reset:
        db.clear_events(project_id)
    inserted = db.save_events(project_id, events)
    if events:
        db.update_scan_cursor(project_id, events[-1].hash)

    return ScanResult(
        project_id=project_id,
        project_name=project_name,
        project_path=str(repo),
        total_events=len(events),
        inserted_events=inserted,
        reset=reset,
    )


def _rule_based_summary(theme: Theme) -> ThemeSummary:
    """Offline fallback: describe a theme from Git facts only."""

    start = theme.started_at.date().isoformat()
    end = theme.ended_at.date().isoformat()
    summary = (
        f"共 {theme.commit_count} 次提交（{start} 至 {end}），"
        f"类型为 {theme.kind}。"
    )
    return ThemeSummary(
        title=theme.title,
        kind=theme.kind,
        summary=summary,
        sources=theme.commit_hashes,
    )


def cmd_review_generate(
    db: DevLogDB,
    path: str | Path | None,
    since: datetime | None = None,
    until: datetime | None = None,
    offline: bool = False,
) -> GenerateResult:
    """Assemble, persist and summarize one structured review draft."""

    repo = _resolve(path)
    _assert_git_repo(repo)
    name = repo.name or "project"
    project_id = db.register_project(name, repo)
    project_name = db.get_project(project_id).name

    events = db.list_events(project_id, since=since, until=until)
    if not events:
        raise CLIUsageError(
            "没有可用的提交记录：请先执行 scan，或检查 --since/--until 范围"
        )

    cluster = cluster_themes(events)
    range_start = events[0].committed_at
    range_end = events[-1].committed_at

    if offline:
        summaries = [_rule_based_summary(theme) for theme in cluster.themes]
        draft = build_review_draft(
            project_name=project_name,
            range_start=range_start,
            range_end=range_end,
            events=events,
            themes=cluster.themes,
            theme_summaries=summaries,
            silence_periods=cluster.silence_periods,
            factual_summaries=True,
        )
    else:
        client = DeepSeekClient()
        summaries = []
        for theme in cluster.themes:
            theme_hash_set = set(theme.commit_hashes)
            theme_events = [
                event for event in events if event.hash in theme_hash_set
            ]
            summaries.append(summarize_theme(theme, theme_events, client))
        draft = build_review_draft(
            project_name=project_name,
            range_start=range_start,
            range_end=range_end,
            events=events,
            themes=cluster.themes,
            theme_summaries=summaries,
            silence_periods=cluster.silence_periods,
            factual_summaries=False,
        )

    draft_id = db.save_review_draft(project_id, draft)
    pending = sum(
        1 for claim in draft.claims if claim.status == ClaimStatus.AI_PENDING
    )
    return GenerateResult(
        draft_id=draft_id,
        project_name=project_name,
        project_path=str(repo),
        range_start=range_start,
        range_end=range_end,
        claim_count=len(draft.claims),
        ai_pending_count=pending,
        question_count=len(draft.questions),
        offline=offline,
    )


def cmd_review_list(
    db: DevLogDB,
    path: str | Path | None = None,
) -> list[ReviewDraftSummary]:
    """Return draft summaries for a project (all projects when no path)."""

    summaries = db.list_review_drafts()
    if path is None:
        return summaries
    repo = _resolve(path)
    return [item for item in summaries if Path(item.project_path) == repo]


def cmd_review_show(db: DevLogDB, draft_id: int) -> StoredReviewDraft:
    """Load one draft with its claims, for review/confirmation."""

    return db.load_review_draft(draft_id)


def cmd_review_confirm(
    db: DevLogDB,
    draft_id: int,
    claim_ids: list[int] | None = None,
    confirm_all: bool = False,
    note: str | None = None,
) -> ConfirmResult:
    """Confirm one or all ai_pending claims. Facts cannot be confirmed."""

    if not confirm_all and not claim_ids:
        raise CLIUsageError("请至少指定一个论断 ID，或使用 --all")

    if confirm_all:
        changed = db.confirm_all_ai_claims(draft_id)
    else:
        changed = 0
        for claim_id in claim_ids or []:
            if db.confirm_review_claim(draft_id, claim_id, note=note):
                changed += 1

    record = db.load_review_draft(draft_id)
    remaining = sum(
        1
        for item in record.draft.claims
        if item.status == ClaimStatus.AI_PENDING
    )
    return ConfirmResult(
        draft_id=draft_id,
        changed=changed,
        remaining_pending=remaining,
    )


def _default_export_path(record: StoredReviewDraft) -> Path:
    safe_name = re.sub(
        r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", record.project_name
    ).strip("_")
    if not safe_name:
        safe_name = "project"
    start = record.draft.range_start.date().isoformat()
    end = record.draft.range_end.date().isoformat()
    return (
        Path(record.project_path)
        / "docs"
        / "retrospectives"
        / f"{safe_name}_{start}_{end}.md"
    )


def cmd_review_export(
    db: DevLogDB,
    draft_id: int,
    output: str | Path | None = None,
) -> Path:
    """Render a draft to Markdown and remember where it was exported."""

    record = db.load_review_draft(draft_id)
    if not record.draft.claims:
        raise CLIUsageError(f"草稿 {draft_id} 没有可导出的内容")

    target = Path(output) if output is not None else _default_export_path(record)
    written = write_markdown(record.draft, target)
    db.mark_draft_exported(draft_id, written)
    return written
