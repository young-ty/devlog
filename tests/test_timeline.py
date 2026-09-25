"""时间线事件流测试：合并、锚点、空档与截断。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from devlog.core.capture.models import (
    AnnotationKind,
    BugRecord,
    BugStatus,
    CommitAnnotation,
    DailyNote,
)
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.storage.database import (
    StoredBugRecord,
    StoredCommitAnnotation,
    StoredDailyNote,
)
from devlog.core.theming.models import SilencePeriod, Theme
from devlog.core.timeline.events import (
    TimelineEventKind,
    build_timeline_stream,
)


TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=TZ)


def make_commit(
    number: int,
    moment: datetime,
    subject: str = "feat: 示例提交",
    noise: NoiseType = NoiseType.NONE,
) -> CommitEvent:
    return CommitEvent(
        hash=f"{number:040d}",
        short_hash=f"{number:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=moment,
        message_subject=subject,
        files_changed=1,
        insertions=1,
        deletions=0,
        parents_count=0,
        noise_type=noise,
    )


def make_annotation(
    identifier: int,
    commit_hash: str,
    created_at: datetime,
    body: str = "这里的重试逻辑踩过坑",
) -> StoredCommitAnnotation:
    return StoredCommitAnnotation(
        id=identifier,
        project_id=1,
        annotation=CommitAnnotation(
            commit_hash=commit_hash,
            kind=AnnotationKind.NOTE,
            body=body,
        ),
        created_at=created_at,
        updated_at=created_at,
    )


def make_bug(identifier: int, captured_at: datetime) -> StoredBugRecord:
    return StoredBugRecord(
        id=identifier,
        project_id=1,
        bug=BugRecord(
            title="打包后首次启动闪退",
            error_text="ModuleNotFoundError",
            status=BugStatus.OPEN,
        ),
        captured_at=captured_at,
        updated_at=captured_at,
    )


def make_note(identifier: int, day: date, summary: str = "今天在调打包") -> StoredDailyNote:
    stamp = datetime(2026, 9, day.day, 22, 0, tzinfo=TZ)
    return StoredDailyNote(
        id=identifier,
        project_id=1,
        note=DailyNote(note_date=day, summary=summary),
        created_at=stamp,
        updated_at=stamp,
    )


def make_theme(
    name: str,
    hashes: tuple[str, ...],
    started_at: datetime,
    ended_at: datetime,
    milestone: bool,
) -> Theme:
    return Theme(
        id=name,
        title=name,
        kind="feature",
        commit_hashes=hashes,
        started_at=started_at,
        ended_at=ended_at,
        commit_count=len(hashes),
        is_milestone_candidate=milestone,
    )


class TimelineStreamTests(unittest.TestCase):
    def test_events_from_every_source_are_merged_in_time_order(self) -> None:
        commits = [make_commit(1, at(1, 9)), make_commit(2, at(3, 9))]
        bugs = [make_bug(1, at(2, 15))]
        notes = [make_note(1, date(2026, 9, 4))]
        annotations = [make_annotation(1, commits[0].hash, at(9, 10))]
        themes = [
            make_theme(
                "主题 1",
                (commits[0].hash, commits[1].hash),
                at(1, 9),
                at(5, 9),
                True,
            )
        ]
        silences = [
            SilencePeriod(started_at=at(3, 9), ended_at=at(7, 9), days=4)
        ]

        stream = build_timeline_stream(
            commits=commits,
            themes=themes,
            silence_periods=silences,
            bugs=bugs,
            notes=notes,
            annotations=annotations,
        )

        self.assertEqual(
            [event.kind for event in stream.events],
            [
                TimelineEventKind.COMMIT,
                TimelineEventKind.ANNOTATION,
                TimelineEventKind.BUG,
                TimelineEventKind.COMMIT,
                TimelineEventKind.GAP,
                TimelineEventKind.NOTE,
                TimelineEventKind.MILESTONE,
            ],
        )
        # 空档从第 2 条提交那一刻起算，所以它紧跟在那条提交后面。
        self.assertEqual(stream.events[3].commit.hash, commits[1].hash)
        self.assertEqual(stream.total_count, 7)
        self.assertEqual(stream.truncated_count, 0)

    def test_annotation_is_anchored_to_commit_time(self) -> None:
        """一周后补写的批注，仍然出现在它评论的那次提交旁边。"""

        commit = make_commit(1, at(1, 9))
        later = make_annotation(1, commit.hash, at(20, 21))

        stream = build_timeline_stream(
            commits=[commit],
            themes=[],
            silence_periods=[],
            annotations=[later],
        )

        annotation_event = stream.events[1]
        self.assertEqual(annotation_event.kind, TimelineEventKind.ANNOTATION)
        self.assertEqual(annotation_event.at, at(1, 9))
        self.assertNotEqual(annotation_event.at, at(20, 21))

    def test_orphan_annotation_is_counted_but_not_shown(self) -> None:
        commit = make_commit(1, at(1, 9))
        orphan = make_annotation(7, "deadbeef" * 5, at(2, 9))

        stream = build_timeline_stream(
            commits=[commit],
            themes=[],
            silence_periods=[],
            annotations=[orphan],
        )

        self.assertEqual(len(stream.events), 1)
        self.assertEqual(stream.orphan_annotation_count, 1)

    def test_daily_note_sorts_after_that_days_commits(self) -> None:
        """笔记只有日期，排到当天最后才是"当天结束时的总结"。"""

        commits = [make_commit(1, at(4, 9)), make_commit(2, at(4, 18))]
        notes = [make_note(1, date(2026, 9, 4))]

        stream = build_timeline_stream(
            commits=commits,
            themes=[],
            silence_periods=[],
            notes=notes,
        )

        self.assertEqual(
            [event.kind for event in stream.events],
            [
                TimelineEventKind.COMMIT,
                TimelineEventKind.COMMIT,
                TimelineEventKind.NOTE,
            ],
        )
        self.assertEqual(stream.events[-1].at.hour, 23)
        self.assertEqual(stream.events[-1].at.minute, 59)

    def test_only_milestone_candidate_themes_produce_events(self) -> None:
        ordinary = make_theme("主题 1", ("a",), at(1, 9), at(2, 9), False)
        release = make_theme("主题 2", ("b",), at(3, 9), at(4, 9), True)

        stream = build_timeline_stream(
            commits=[],
            themes=[ordinary, release],
            silence_periods=[],
        )

        self.assertEqual(len(stream.events), 1)
        self.assertEqual(stream.events[0].kind, TimelineEventKind.MILESTONE)
        self.assertEqual(stream.events[0].theme.id, "主题 2")

    def test_commit_sorts_before_annotation_at_the_same_moment(self) -> None:
        """同一时刻的顺序必须固定，否则每刷新一次卡片位置都会跳。"""

        commit = make_commit(1, at(1, 9))
        annotations = [
            make_annotation(1, commit.hash, at(1, 9)),
            make_annotation(2, commit.hash, at(1, 9)),
        ]

        stream = build_timeline_stream(
            commits=[commit],
            themes=[],
            silence_periods=[],
            annotations=annotations,
        )

        self.assertEqual(
            [event.kind for event in stream.events],
            [
                TimelineEventKind.COMMIT,
                TimelineEventKind.ANNOTATION,
                TimelineEventKind.ANNOTATION,
            ],
        )
        self.assertEqual(
            [event.key for event in stream.events],
            ["commit:" + commit.hash, "annotation:1", "annotation:2"],
        )

    def test_limit_keeps_the_most_recent_events(self) -> None:
        commits = [make_commit(number, at(number)) for number in range(1, 11)]

        stream = build_timeline_stream(
            commits=commits,
            themes=[],
            silence_periods=[],
            limit=4,
        )

        self.assertEqual(stream.total_count, 10)
        self.assertEqual(stream.truncated_count, 6)
        self.assertEqual(len(stream.events), 4)
        self.assertEqual([event.at.day for event in stream.events], [7, 8, 9, 10])

    def test_limit_none_keeps_everything(self) -> None:
        commits = [make_commit(number, at(number)) for number in range(1, 4)]

        stream = build_timeline_stream(
            commits=commits,
            themes=[],
            silence_periods=[],
            limit=None,
        )

        self.assertEqual(len(stream.events), 3)
        self.assertEqual(stream.truncated_count, 0)

    def test_naive_timestamps_do_not_break_sorting(self) -> None:
        """只要有一个时间戳没带时区，直接比较就会抛 TypeError。"""

        aware = make_commit(1, at(1, 9))
        naive_commit = make_commit(2, datetime(2026, 9, 2, 9, 0))
        naive_bug = make_bug(1, datetime(2026, 9, 3, 15, 0))

        stream = build_timeline_stream(
            commits=[aware, naive_commit],
            themes=[],
            silence_periods=[],
            bugs=[naive_bug],
        )

        self.assertEqual(len(stream.events), 3)
        self.assertTrue(
            all(event.at.tzinfo is not None for event in stream.events)
        )

    def test_noise_commits_reach_the_frontend_for_filtering(self) -> None:
        clean = make_commit(1, at(1, 9))
        noisy = make_commit(2, at(2, 9), "wip: 没写完", NoiseType.WIP)

        stream = build_timeline_stream(
            commits=[clean, noisy],
            themes=[],
            silence_periods=[],
        )

        self.assertEqual(len(stream.events), 2)
        self.assertEqual(stream.events[1].commit.noise_type, NoiseType.WIP)

    def test_empty_input_produces_empty_stream(self) -> None:
        stream = build_timeline_stream(
            commits=[],
            themes=[],
            silence_periods=[],
        )

        self.assertEqual(stream.events, [])
        self.assertEqual(stream.total_count, 0)
        self.assertEqual(stream.truncated_count, 0)
        self.assertEqual(stream.orphan_annotation_count, 0)

    def test_building_twice_is_deterministic(self) -> None:
        commits = [make_commit(1, at(1, 9)), make_commit(2, at(2, 9))]
        annotations = [
            make_annotation(1, commits[0].hash, at(5, 9)),
            make_annotation(2, commits[0].hash, at(6, 9)),
        ]
        silences = [
            SilencePeriod(started_at=at(1, 9), ended_at=at(8, 9), days=7)
        ]

        first = build_timeline_stream(
            commits=commits,
            themes=[],
            silence_periods=silences,
            annotations=annotations,
        )
        second = build_timeline_stream(
            commits=commits,
            themes=[],
            silence_periods=silences,
            annotations=list(reversed(annotations)),
        )

        self.assertEqual(first.events, second.events)


if __name__ == "__main__":
    unittest.main()
