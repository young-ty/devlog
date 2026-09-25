"""把 Git 提交与人工记录合并成一条可渲染的时间线事件流。

Git 只回答"提交了什么"；Bug 捕获、每日笔记、commit 批注回答"当时
遇到了什么"。复盘时人需要的是一条按发生顺序排好的线索，这个模块
负责把散落在多张表里的记录合并成一条流，并把"这段时间没有提交"
显式标成一个空档事件。

合并放在这里而不是前端，是为了让排序规则和空档口径只有一份实现：
空档直接复用主题聚类算出的静默期，前端拿到的就是排好序的数组。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Sequence

from devlog.core.git_source.models import CommitEvent
from devlog.core.storage.database import (
    StoredBugRecord,
    StoredCommitAnnotation,
    StoredDailyNote,
)
from devlog.core.theming.models import SilencePeriod, Theme


# 时间线上限：每个事件都会渲染成一段绝对定位的 DOM，几千个节点会让
# 首屏和拖动都卡住。超过上限时只保留最近的这些，其余交给调用方提示。
DEFAULT_EVENT_LIMIT = 500

# 每日笔记只有日期没有时刻。排到当天最后，读起来才是"这一天结束时
# 写下的总结"，而不是"当天开工之前就写好了"。
_NOTE_TIME = time(23, 59)


class TimelineEventKind(str, enum.Enum):
    """时间线上一个节点承载的是哪一类事实。"""

    COMMIT = "commit"
    BUG = "bug"
    NOTE = "note"
    ANNOTATION = "annotation"
    MILESTONE = "milestone"
    GAP = "gap"


# 同一时刻可能堆着多个事件（批注就锚在 commit 的提交时刻上），用固定
# 次序保证每次渲染顺序完全一致，而不是依赖排序算法的稳定性。
_KIND_ORDER = {
    TimelineEventKind.COMMIT: 0,
    TimelineEventKind.ANNOTATION: 1,
    TimelineEventKind.BUG: 2,
    TimelineEventKind.NOTE: 3,
    TimelineEventKind.MILESTONE: 4,
    TimelineEventKind.GAP: 5,
}


@dataclass(frozen=True)
class TimelineEvent:
    """时间线上的一个节点，payload 字段按 kind 取用。"""

    kind: TimelineEventKind
    at: datetime
    key: str
    commit: CommitEvent | None = None
    bug: StoredBugRecord | None = None
    note: StoredDailyNote | None = None
    annotation: StoredCommitAnnotation | None = None
    theme: Theme | None = None
    gap: SilencePeriod | None = None


@dataclass(frozen=True)
class TimelineStream:
    """合并结果，同时说明被截掉了多少、有多少批注没有落脚点。"""

    events: list[TimelineEvent]
    total_count: int
    truncated_count: int
    orphan_annotation_count: int


def _as_utc_aware(moment: datetime) -> datetime:
    """把没有时区的时间戳按 UTC 补齐，避免比较时直接抛异常。

    提交时间是 Git 给的（带时区偏移），记忆层的时间戳由本机写入
    （UTC）。两者混排时只要有一个是 naive，Python 会拒绝比较，
    整个时间线页面都会打不开，所以这里统一兜一下。
    """

    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _note_moment(value: date | str) -> datetime:
    """每日笔记的排序时刻：当天 23:59。"""

    day = value if isinstance(value, date) else date.fromisoformat(value)
    return datetime.combine(day, _NOTE_TIME, tzinfo=timezone.utc)


def build_timeline_stream(
    *,
    commits: Sequence[CommitEvent],
    themes: Sequence[Theme],
    silence_periods: Sequence[SilencePeriod],
    bugs: Sequence[StoredBugRecord] = (),
    notes: Sequence[StoredDailyNote] = (),
    annotations: Sequence[StoredCommitAnnotation] = (),
    limit: int | None = DEFAULT_EVENT_LIMIT,
) -> TimelineStream:
    """把各来源的记录合并成一条按时间排好的事件流。

    批注挂在它评论的那次 commit 的提交时刻上，而不是批注自身的创建
    时刻：否则一周后补写的批注会跑到时间线最右端，和它评论的提交相隔
    很远，读起来没有上下文。找不到对应 commit 的孤儿批注不进时间线，
    只统计数量，交给调用方单独展示。
    """

    commit_at = {
        event.hash: _as_utc_aware(event.committed_at) for event in commits
    }

    events: list[TimelineEvent] = [
        TimelineEvent(
            kind=TimelineEventKind.COMMIT,
            at=_as_utc_aware(event.committed_at),
            key=f"commit:{event.hash}",
            commit=event,
        )
        for event in commits
    ]

    orphan_annotations = 0
    for stored in annotations:
        anchored = commit_at.get(stored.annotation.commit_hash)
        if anchored is None:
            orphan_annotations += 1
            continue
        events.append(
            TimelineEvent(
                kind=TimelineEventKind.ANNOTATION,
                at=anchored,
                key=f"annotation:{stored.id}",
                annotation=stored,
            )
        )

    for stored in bugs:
        events.append(
            TimelineEvent(
                kind=TimelineEventKind.BUG,
                at=_as_utc_aware(stored.captured_at),
                key=f"bug:{stored.id}",
                bug=stored,
            )
        )

    for stored in notes:
        events.append(
            TimelineEvent(
                kind=TimelineEventKind.NOTE,
                at=_note_moment(stored.note.note_date),
                key=f"note:{stored.id}",
                note=stored,
            )
        )

    for theme in themes:
        if not theme.is_milestone_candidate:
            continue
        events.append(
            TimelineEvent(
                kind=TimelineEventKind.MILESTONE,
                at=_as_utc_aware(theme.ended_at),
                key=f"milestone:{theme.id}",
                theme=theme,
            )
        )

    for period in silence_periods:
        started = _as_utc_aware(period.started_at)
        events.append(
            TimelineEvent(
                kind=TimelineEventKind.GAP,
                at=started,
                key=f"gap:{started.isoformat()}",
                gap=period,
            )
        )

    events.sort(key=lambda item: (item.at, _KIND_ORDER[item.kind], item.key))

    total = len(events)
    if limit is not None and limit > 0 and total > limit:
        events = events[total - limit :]

    return TimelineStream(
        events=events,
        total_count=total,
        truncated_count=total - len(events),
        orphan_annotation_count=orphan_annotations,
    )
