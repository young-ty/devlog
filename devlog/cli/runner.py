"""CLI 与（后续的）本地 API 共用的业务编排。

这些函数完全不知道 argparse：它们接收数据库与路径/选项，返回普通结果
对象。main.py 只负责把终端输入翻译成这里的调用并打印结果。
"""

from __future__ import annotations

import re
import subprocess
import platform
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from devlog.core.capture.models import (
    AnnotationKind,
    BugRecord,
    BugStatus,
    CommitAnnotation,
    DailyNote,
)
from devlog.core.digest.day import DayDigest, build_day_digest, system_timezone
from devlog.core.git_source.scanner import GitSourceError, scan_repository
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.deepseek import DeepSeekClient
from devlog.core.llm.themes import (
    complete_json_with_retry,
    rule_based_summary,
    summarize_assets,
    summarize_theme,
)
from devlog.core.llm.translation import translate_commit_subjects
from devlog.core.review.engine import build_review_draft
from devlog.core.review.document import FinalDocument, build_final_document
from devlog.core.review.markdown import write_markdown
from devlog.core.review.models import (
    GENERATION_MODE_AI,
    GENERATION_MODE_OFFLINE,
    ClaimStatus,
    ReviewQuestion,
)
from devlog.core.storage.database import (
    DevLogDB,
    ReviewDraftSummary,
    StoredBugRecord,
    StoredCommitAnnotation,
    StoredDailyNote,
    StoredReviewDraft,
)
from devlog.core.theming.cluster import cluster_themes
from devlog.core.theming.models import SilencePeriod, Theme
from devlog.core.timeline.events import (
    DEFAULT_EVENT_LIMIT,
    TimelineEvent,
    build_timeline_stream,
)


class CLIUsageError(ValueError):
    """当请求的动作无法执行时抛出。"""


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
    # 本次归纳出的可复用资产候选数；离线模式恒为 0。
    asset_count: int
    offline: bool


@dataclass(frozen=True)
class ConfirmResult:
    draft_id: int
    changed: int
    remaining_pending: int


@dataclass(frozen=True)
class TimelineResult:
    project_id: int
    project_name: str
    project_path: str
    range_start: datetime | None
    range_end: datetime | None
    commits: list[CommitEvent]
    themes: list[Theme]
    silence_periods: list[SilencePeriod]
    translations: dict[str, str]


@dataclass(frozen=True)
class TranslationResult:
    project_id: int
    project_name: str
    project_path: str
    translated_count: int
    remaining_count: int


@dataclass(frozen=True)
class TimelineStreamResult:
    """合并后的时间线事件流，供 API 直接序列化。"""

    project_id: int
    project_name: str
    project_path: str
    events: list[TimelineEvent]
    total_count: int
    truncated_count: int
    orphan_annotation_count: int
    translations: dict[str, str]


def _resolve(path: str | Path | None) -> Path:
    raw = Path(path) if path is not None else Path.cwd()
    return raw.expanduser().resolve()


def _assert_git_repo(repo: Path) -> None:
    """路径不是 Git 工作区时抛出友好错误。"""

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


def is_git_repo(path: str | Path) -> bool:
    """路径是不是 Git 工作区；只回答"是/不是"，不抛业务异常。

    给「选完文件夹立刻给提示」这种场景用：前端刚选完目录，
    需要马上告诉用户"这里没有 .git"，而不是等注册时才报错。
    复用 _assert_git_repo，保证命令行和网页的判定标准完全一致。
    """

    try:
        _assert_git_repo(Path(path))
    except (CLIUsageError, GitSourceError):
        return False
    return True


def cmd_init(
    db: DevLogDB,
    path: str | Path | None,
    name: str | None = None,
) -> InitResult:
    """注册一个仓库；重复注册同一路径不会产生副作用。"""

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
    """把完整 Git 历史扫描进缓存数据库。"""

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


def cmd_review_generate(
    db: DevLogDB,
    path: str | Path | None,
    since: datetime | None = None,
    until: datetime | None = None,
    offline: bool = False,
) -> GenerateResult:
    """组装、持久化并汇总一份结构化复盘草稿。"""

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
    bug_records = [record.bug for record in db.list_bug_records(project_id)]

    if offline:
        summaries = [rule_based_summary(theme) for theme in cluster.themes]
        assets = []
        draft = build_review_draft(
            project_name=project_name,
            range_start=range_start,
            range_end=range_end,
            events=events,
            themes=cluster.themes,
            theme_summaries=summaries,
            silence_periods=cluster.silence_periods,
            factual_summaries=True,
            bug_records=bug_records,
            generation_mode=GENERATION_MODE_OFFLINE,
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
        assets = summarize_assets(cluster.themes, summaries, client)
        draft = build_review_draft(
            project_name=project_name,
            range_start=range_start,
            range_end=range_end,
            events=events,
            themes=cluster.themes,
            theme_summaries=summaries,
            silence_periods=cluster.silence_periods,
            factual_summaries=False,
            bug_records=bug_records,
            asset_summaries=assets,
            generation_mode=GENERATION_MODE_AI,
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
        asset_count=len(assets),
        offline=offline,
    )


def cmd_review_list(
    db: DevLogDB,
    path: str | Path | None = None,
) -> list[ReviewDraftSummary]:
    """返回某项目的草稿摘要（未给路径时返回全部项目）。"""

    summaries = db.list_review_drafts()
    if path is None:
        return summaries
    repo = _resolve(path)
    return [item for item in summaries if Path(item.project_path) == repo]


def cmd_timeline(db: DevLogDB, project_id: int) -> TimelineResult:
    """返回缓存的 commit 时间线及其规则版主题视图。"""

    project = db.get_project(project_id)
    events = db.list_events(project_id, include_noise=True)
    content_events = [
        event for event in events if event.noise_type == NoiseType.NONE
    ]
    cluster = cluster_themes(content_events)
    translations = db.list_commit_translations(project_id)
    return TimelineResult(
        project_id=project.project_id,
        project_name=project.name,
        project_path=project.path,
        range_start=events[0].committed_at if events else None,
        range_end=events[-1].committed_at if events else None,
        commits=events,
        themes=cluster.themes,
        silence_periods=cluster.silence_periods,
        translations=translations,
    )


def cmd_timeline_events(
    db: DevLogDB,
    project_id: int,
    limit: int | None = DEFAULT_EVENT_LIMIT,
) -> TimelineStreamResult:
    """把提交与人工记录合并成一条排好序的时间线事件流。

    主题聚类与静默期直接复用 cmd_timeline 的同一套规则，避免"时间线说
    没有空档、复盘页说有静默期"这种两套口径的问题。
    """

    project = db.get_project(project_id)
    events = db.list_events(project_id, include_noise=True)
    cluster = cluster_themes(
        [event for event in events if event.noise_type == NoiseType.NONE]
    )
    stream = build_timeline_stream(
        commits=events,
        themes=cluster.themes,
        silence_periods=cluster.silence_periods,
        bugs=db.list_bug_records(project_id),
        notes=db.list_daily_notes(project_id),
        annotations=db.list_commit_annotations(project_id),
        limit=limit,
    )
    return TimelineStreamResult(
        project_id=project.project_id,
        project_name=project.name,
        project_path=project.path,
        events=stream.events,
        total_count=stream.total_count,
        truncated_count=stream.truncated_count,
        orphan_annotation_count=stream.orphan_annotation_count,
        translations=db.list_commit_translations(project_id),
    )


def cmd_translate_commits(db: DevLogDB, project_id: int) -> TranslationResult:
    """翻译尚未翻译的缓存 commit subject，并把结果缓存。"""

    project = db.get_project(project_id)
    events = db.list_events(project_id, include_noise=True)
    if not events:
        return TranslationResult(
            project_id=project_id,
            project_name=project.name,
            project_path=project.path,
            translated_count=0,
            remaining_count=0,
        )

    cached = db.list_commit_translations(project_id)
    pending = [
        (event.hash, event.message_subject)
        for event in events
        if event.hash not in cached
    ]
    if not pending:
        return TranslationResult(
            project_id=project_id,
            project_name=project.name,
            project_path=project.path,
            translated_count=0,
            remaining_count=0,
        )

    translated = translate_commit_subjects(DeepSeekClient(), pending)
    inserted = db.save_commit_translations(project_id, translated)
    return TranslationResult(
        project_id=project_id,
        project_name=project.name,
        project_path=project.path,
        translated_count=inserted,
        remaining_count=len(pending) - len(translated),
    )


def cmd_review_show(db: DevLogDB, draft_id: int) -> StoredReviewDraft:
    """加载一份草稿及其论断，供查看/确认使用。"""

    return db.load_review_draft(draft_id)


@dataclass(frozen=True)
class ReviewDocumentResult:
    """成稿文档 + 它的项目上下文，供 API 直接序列化。"""

    record: StoredReviewDraft
    document: FinalDocument


def cmd_review_document(db: DevLogDB, draft_id: int) -> ReviewDocumentResult:
    """把草稿整理成成稿文档：只收人类认过的内容。

    网页和将来的 CLI 都走这一条路，成稿规则就不会有第二份实现。
    草稿只读一次，免得两处加载结果对不上。
    """

    record = cmd_review_show(db, draft_id)
    return ReviewDocumentResult(
        record=record,
        document=build_final_document(record.draft),
    )


def cmd_review_finalize(
    db: DevLogDB,
    draft_id: int,
    finalized: bool = True,
) -> StoredReviewDraft:
    """定稿或撤回定稿，返回更新后的草稿。

    定稿只是"这份我认了"的标记，内容照样能改。返回整条记录是为了让调用方
    直接拿到新状态和新时间戳，不用再查一次。
    """

    db.set_review_finalized(draft_id, finalized)
    return cmd_review_show(db, draft_id)


def cmd_review_confirm(
    db: DevLogDB,
    draft_id: int,
    claim_ids: list[int] | None = None,
    confirm_all: bool = False,
    note: str | None = None,
) -> ConfirmResult:
    """确认一条或多条 ai_pending 论断。事实论断不可被确认。"""

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


def cmd_review_answer(
    db: DevLogDB,
    draft_id: int,
    question_number: int,
    answer: str,
) -> ReviewQuestion:
    """保存某条引导问题的回答，返回更新后的问题。

    问题编号从 1 开始，和网页/导出文档里显示的编号一致。
    """

    record = db.load_review_draft(draft_id)
    total = len(record.draft.questions)
    if total == 0:
        raise CLIUsageError("这份草稿没有引导问题")
    if question_number < 1 or question_number > total:
        raise CLIUsageError(
            f"问题序号超出范围：{question_number}（本草稿共 {total} 个问题）"
        )

    db.save_draft_answer(draft_id, question_number, answer)
    updated = db.load_review_draft(draft_id)
    return updated.draft.questions[question_number - 1]


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
    """把草稿渲染为 Markdown，并记录导出位置。"""

    record = db.load_review_draft(draft_id)
    if not record.draft.claims:
        raise CLIUsageError(f"草稿 {draft_id} 没有可导出的内容")

    target = Path(output) if output is not None else _default_export_path(record)
    written = write_markdown(
        record.draft,
        target,
        status=record.status,
        finalized_at=record.finalized_at,
    )
    db.mark_draft_exported(draft_id, written)
    return written


def cmd_review_delete(db: DevLogDB, draft_id: int) -> bool:
    """删除一份草稿；不存在时返回 False 而不是抛错。

    返回布尔值而不是抛异常，是为了让 DELETE 接口能自然地返回 404，
    也让"并发重复删除"不会变成一个 500。
    """

    return db.delete_review_draft(draft_id)


# ----------------------------------------------------------------------
# 记忆层：每日笔记 / Bug 捕获 / commit 批注
# ----------------------------------------------------------------------

_TITLE_HINT_WORDS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "fatal",
    "cannot",
    "undefined",
    "refused",
    "invalid",
)


def _fallback_bug_title(title: str, error_text: str) -> str:
    """没给标题时，从报错文本里挑一句最像错误信息的话。"""

    if title and title.strip():
        return title.strip()
    meaningful = [line.strip() for line in error_text.splitlines() if line.strip()]
    for line in meaningful:
        lowered = line.lower()
        if any(word in lowered for word in _TITLE_HINT_WORDS):
            return line[:80]
    return meaningful[-1][:80] if meaningful else "未命名 Bug"


def _environment_summary() -> str:
    """采集运行环境摘要（操作系统 + Python 版本）。"""

    return (
        f"{platform.system()} {platform.release()}, "
        f"Python {platform.python_version()}"
    )


def _git_snapshot(repo: Path) -> tuple[str, str]:
    """尽力采集 git 现场（HEAD + 工作区摘要），失败也不抛错。"""

    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError:
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    head = run("rev-parse", "HEAD")
    short = run("rev-parse", "--short", "HEAD")
    git_head = f"{head} ({short})" if head and short else head

    porcelain = run("status", "--porcelain")
    lines = [line for line in porcelain.splitlines() if line.strip()]
    if not lines:
        git_status = "clean"
    else:
        changed = sum(1 for line in lines if not line.startswith("??"))
        untracked = sum(1 for line in lines if line.startswith("??"))
        git_status = f"{changed} files changed, {untracked} untracked"
    return git_head, git_status


def cmd_daily_note_save(
    db: DevLogDB,
    project_id: int,
    note: DailyNote,
) -> StoredDailyNote:
    """保存（有则更新）某一天的项目笔记，并返回持久化结果。"""

    db.upsert_daily_note(project_id, note)
    stored = db.get_daily_note(project_id, note.note_date)
    if stored is None:
        raise DatabaseError("每日笔记保存后读取失败")
    return stored


def cmd_daily_note_list(
    db: DevLogDB,
    project_id: int,
    since: date | None = None,
    until: date | None = None,
) -> list[StoredDailyNote]:
    """列出某个项目的每日笔记，新的在前。"""

    return db.list_daily_notes(project_id, since=since, until=until)


def cmd_day_digest(
    db: DevLogDB,
    project_id: int,
    day: date,
    tz: timezone | None = None,
) -> DayDigest:
    """汇总某一天的事实：提交、Bug、已有笔记。

    「哪一天」以本机时区为准。查询时故意左右各放宽一天，再交给
    digest 模块按本地日历日精确过滤：Git 提交带自己的时区偏移，
    用本地边界直接卡 since/until 会在边界上漏记录。
    """

    db.get_project(project_id)  # 项目不存在时抛出 DatabaseError（接口转 404）
    zone = tz if tz is not None else system_timezone()
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)

    commits = db.list_events(
        project_id,
        since=start - timedelta(days=1),
        until=end + timedelta(days=1),
    )
    return build_day_digest(
        day,
        commits=commits,
        bugs=db.list_bug_records(project_id),
        note=db.get_daily_note(project_id, day),
        has_cached_commits=db.has_cached_events(project_id),
        tz=zone,
    )


def cmd_bug_capture(
    db: DevLogDB,
    project_id: int,
    title: str = "",
    error_text: str = "",
    title_source: str = "manual",
) -> StoredBugRecord:
    """捕获一条 Bug：自动采集环境与 Git 现场，标题缺失时自动兜底。"""

    project = db.get_project(project_id)
    repo = Path(project.path)
    git_head, git_status = _git_snapshot(repo)
    resolved_title = _fallback_bug_title(title, error_text)
    bug = BugRecord(
        title=resolved_title,
        title_source=title_source,
        error_text=error_text,
        environment=_environment_summary(),
        git_head=git_head,
        git_status=git_status,
    )
    bug_id = db.create_bug_record(project_id, bug)
    return db.get_bug_record(bug_id)


def cmd_bug_list(
    db: DevLogDB,
    project_id: int,
    status: BugStatus | None = None,
) -> list[StoredBugRecord]:
    """列出某项目的 Bug 记录，可按状态过滤。"""

    return db.list_bug_records(project_id, status=status)


def cmd_bug_update(
    db: DevLogDB,
    bug_id: int,
    *,
    title: str | None = None,
    title_source: str | None = None,
    root_cause: str | None = None,
    solution: str | None = None,
    status: BugStatus | None = None,
) -> StoredBugRecord:
    """更新 Bug 的人为补充字段；现场快照字段不可改。"""

    db.update_bug_record(
        bug_id,
        title=title,
        title_source=title_source,
        root_cause=root_cause,
        solution=solution,
        status=status,
    )
    return db.get_bug_record(bug_id)


def cmd_bug_delete(db: DevLogDB, bug_id: int) -> bool:
    """删除一条 Bug 记录。"""

    return db.delete_bug_record(bug_id)


def cmd_suggest_bug_title(error_text: str, environment: str = "") -> str:
    """让 DeepSeek 根据报错内容生成一句话中文标题建议。"""

    client = DeepSeekClient()
    prompt = (
        "根据下面的报错与环境信息，生成一句 10~25 个字的简体中文 Bug "
        "标题，概括问题本身，不写解决方案。只返回 JSON："
        '{"title": "..."}\n\n'
        f"环境信息：{environment or '未知'}\n\n报错内容：\n{error_text}"
    )
    data = complete_json_with_retry(client, prompt)
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise LLMError("AI 没有返回有效的标题建议")
    return title.strip()


def cmd_annotation_add(
    db: DevLogDB,
    project_id: int,
    commit_hash: str,
    kind: AnnotationKind,
    body: str,
) -> StoredCommitAnnotation:
    """给某项目已缓存的 commit 添加一条批注。"""

    annotation_id = db.add_commit_annotation(
        project_id,
        CommitAnnotation(commit_hash=commit_hash, kind=kind, body=body),
    )
    return db.get_commit_annotation(annotation_id)


def cmd_annotation_list(
    db: DevLogDB,
    project_id: int,
    commit_hash: str | None = None,
    orphan: bool = False,
) -> list[StoredCommitAnnotation]:
    """列出项目批注；orphan=True 时只返回挂靠不上的孤儿批注。"""

    if orphan:
        return db.list_orphan_commit_annotations(project_id)
    return db.list_commit_annotations(project_id, commit_hash=commit_hash)


def cmd_annotation_update(
    db: DevLogDB,
    annotation_id: int,
    *,
    kind: AnnotationKind | None = None,
    body: str | None = None,
) -> StoredCommitAnnotation:
    """编辑一条批注的 kind 或正文。"""

    db.update_commit_annotation(annotation_id, kind=kind, body=body)
    return db.get_commit_annotation(annotation_id)


def cmd_annotation_delete(db: DevLogDB, annotation_id: int) -> bool:
    """删除一条批注。"""

    return db.delete_commit_annotation(annotation_id)
