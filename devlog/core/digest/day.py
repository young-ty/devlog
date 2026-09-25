"""当日小结：把某一天发生的事凑成一屏，供写每日复盘时对照。

每日复盘最难的一步不是写，是想起当天干了什么。Git 缓存里本来就有提交，
Bug 表里本来就有捕获记录，把它们按"当天"归拢一次，写笔记时就不用凭
记忆硬凑——这也正是这个工具存在的理由。

这里只做**事实归并**：不调模型、不猜原因、不下结论，所以既不花 token，
也不存在幻觉风险。哪一天算"当天"、哪些提交算数、草稿长什么样，规则都
放在这个模块里，界面和 CLI 共用同一份，免得两边口径不一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence

from devlog.core.git_source.models import CommitEvent
from devlog.core.storage.database import StoredBugRecord, StoredDailyNote


def system_timezone() -> timezone:
    """本机时区。

    "当天"以开发者手腕上的表为准：同一天在 UTC+8 和 UTC-5 是两个不同的
    区间。本机跑的工具直接用本机时区，不引入额外配置。
    """

    local = datetime.now().astimezone().tzinfo
    return local if local is not None else timezone.utc


def _to_local(moment: datetime, zone: timezone) -> datetime:
    """把时间戳换算到目标时区。

    没有时区的时间戳按 UTC 补齐，与时间线模块的口径保持一致：混排时只要
    有一个是 naive，比较就会直接抛异常，整个页面打不开。
    """

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone)


@dataclass(frozen=True)
class DayCommit:
    """当天的一次提交。时间已经换算到目标时区，可以直接显示。"""

    short_hash: str
    subject: str
    committed_at: datetime
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


@dataclass(frozen=True)
class DayBug:
    """当天捕获的一条 Bug：只带定位和状态，详情回 Bug 页面看。"""

    id: int
    title: str
    status: str
    # 捕获时刻（已换算到目标时区）：当天小结要把它插进时间顺序里，
    # 只说"那天有个 Bug"看不出它出现在哪个环节。
    captured_at: datetime | None = None


@dataclass(frozen=True)
class DayDigest:
    """某一天的事实汇总。"""

    day: date
    commits: tuple[DayCommit, ...] = ()
    bugs: tuple[DayBug, ...] = ()
    note: StoredDailyNote | None = None
    # 这个仓库有没有任何缓存提交。用来区分「当天确实没干活」和
    # 「根本还没扫描过」——这两种情况给用户的提示完全不同。
    has_cached_commits: bool = True

    @property
    def commit_count(self) -> int:
        return len(self.commits)

    @property
    def bug_count(self) -> int:
        return len(self.bugs)

    @property
    def file_count(self) -> int:
        """当天改动过的文件数。同一天多个提交改了同一个文件会重复计数：
        Git 的 numstat 是按提交给的，这里不做跨提交去重，宁可保守。"""

        return sum(item.files_changed for item in self.commits)

    @property
    def insertions(self) -> int:
        return sum(item.insertions for item in self.commits)

    @property
    def deletions(self) -> int:
        return sum(item.deletions for item in self.commits)

    @property
    def first_commit_at(self) -> datetime | None:
        return self.commits[0].committed_at if self.commits else None

    @property
    def last_commit_at(self) -> datetime | None:
        return self.commits[-1].committed_at if self.commits else None

    @property
    def active_minutes(self) -> int | None:
        """首末提交的间隔。

        注意它不是"工作时长"：两次提交中间在开会、吃饭都算在里面。
        界面上只能叫"跨度"，不能叫"工时"。
        """

        if not self.commits:
            return None
        span = self.commits[-1].committed_at - self.commits[0].committed_at
        return int(span.total_seconds() // 60)

    @property
    def has_note(self) -> bool:
        return self.note is not None

    @property
    def is_empty(self) -> bool:
        return not self.commits and not self.bugs

    @property
    def draft_text(self) -> str:
        """能直接填进「今天做了什么」的草稿。

        只把事实排成列表，不写成句子：句子该由写的人自己组织，
        而且一旦开始"润色"，就是在替用户编没发生过的因果。
        """

        if not self.commits:
            return ""
        lines = [
            f"- {item.committed_at.strftime('%H:%M')} {item.subject}"
            f"（{item.short_hash}）"
            for item in self.commits
        ]
        if self.bugs:
            titles = "、".join(bug.title for bug in self.bugs)
            lines.append(f"- 期间处理的问题：{titles}")
        return "\n".join(lines)


def build_day_digest(
    day: date,
    *,
    commits: Sequence[CommitEvent],
    bugs: Sequence[StoredBugRecord] = (),
    note: StoredDailyNote | None = None,
    has_cached_commits: bool = True,
    tz: timezone | None = None,
) -> DayDigest:
    """把各来源的记录按"哪一天"过滤后汇总起来。

    过滤按目标时区的日历日做，并在这里完成，而不是把 since/until 交给
    存储层：Git 提交带自己的时区偏移，跨夏令时或跨时区协作时，边界上
    差一秒结果就不同，集中在一处判断才好解释。
    """

    zone = tz if tz is not None else system_timezone()

    day_commits = sorted(
        (
            DayCommit(
                short_hash=event.short_hash,
                subject=event.message_subject,
                committed_at=_to_local(event.committed_at, zone),
                files_changed=event.files_changed,
                insertions=event.insertions,
                deletions=event.deletions,
            )
            for event in commits
            if _to_local(event.committed_at, zone).date() == day
        ),
        key=lambda item: item.committed_at,
    )

    day_bugs = tuple(
        DayBug(
            id=stored.id,
            title=stored.bug.title,
            status=stored.bug.status.value,
            captured_at=_to_local(stored.captured_at, zone),
        )
        for stored in bugs
        if _to_local(stored.captured_at, zone).date() == day
    )

    return DayDigest(
        day=day,
        commits=tuple(day_commits),
        bugs=day_bugs,
        note=note,
        has_cached_commits=has_cached_commits,
    )
