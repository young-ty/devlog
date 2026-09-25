"""当日小结测试：哪一天算"当天"、哪些记录进小结、草稿长什么样。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from devlog.cli import runner
from devlog.core.capture.models import BugRecord, BugStatus, DailyNote
from devlog.core.digest.day import build_day_digest
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.storage.database import DevLogDB, StoredBugRecord


TZ = timezone(timedelta(hours=8))
UTC = timezone.utc


def moment(day: int, hour: int = 9, minute: int = 0, tz: timezone = TZ) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=tz)


def make_commit(
    number: int,
    when: datetime,
    subject: str = "feat: add login page",
    *,
    files: int = 1,
    insertions: int = 10,
    deletions: int = 2,
) -> CommitEvent:
    return CommitEvent(
        hash=f"{number:040d}",
        short_hash=f"{number:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=when,
        message_subject=subject,
        files_changed=files,
        insertions=insertions,
        deletions=deletions,
        parents_count=0,
        noise_type=NoiseType.NONE,
    )


def make_bug(bug_id: int, captured_at: datetime, title: str = "启动就报错") -> StoredBugRecord:
    return StoredBugRecord(
        id=bug_id,
        project_id=1,
        bug=BugRecord(title=title, status=BugStatus.OPEN),
        captured_at=captured_at,
        updated_at=captured_at,
    )


class DayFilterTests(unittest.TestCase):
    """日期归属规则：按目标时区的日历日算，边界不靠存储层的字符串比较。"""

    def test_only_the_requested_day_is_included(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[
                make_commit(1, moment(9)),
                make_commit(2, moment(10, 9)),
                make_commit(3, moment(10, 18)),
                make_commit(4, moment(11)),
            ],
            tz=TZ,
        )
        self.assertEqual(
            [item.short_hash for item in digest.commits],
            [f"{2:07d}", f"{3:07d}"],
        )

    def test_day_boundary_follows_the_target_timezone(self) -> None:
        """00:30（+08:00）在东八区是 10 号，在 UTC 还是 9 号。"""

        events = [make_commit(1, moment(10, 0, 30))]
        east = build_day_digest(date(2026, 9, 10), commits=events, tz=TZ)
        utc = build_day_digest(date(2026, 9, 10), commits=events, tz=UTC)
        self.assertEqual(east.commit_count, 1)
        self.assertEqual(utc.commit_count, 0)
        self.assertEqual(
            build_day_digest(date(2026, 9, 9), commits=events, tz=UTC).commit_count,
            1,
        )

    def test_naive_timestamp_is_treated_as_utc(self) -> None:
        """混进一个没有时区的时间戳时，页面不能直接崩掉。"""

        naive = make_commit(1, datetime(2026, 9, 10, 9, 0))
        digest = build_day_digest(date(2026, 9, 10), commits=[naive], tz=TZ)
        self.assertEqual(digest.commit_count, 1)
        self.assertEqual(digest.commits[0].committed_at.tzinfo, TZ)

    def test_commits_are_sorted_by_time(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[
                make_commit(2, moment(10, 18)),
                make_commit(1, moment(10, 9)),
            ],
            tz=TZ,
        )
        self.assertEqual(
            [item.committed_at.hour for item in digest.commits], [9, 18]
        )


class StatsTests(unittest.TestCase):
    def test_numbers_add_up_across_commits(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[
                make_commit(1, moment(10, 9), files=3, insertions=100, deletions=5),
                make_commit(2, moment(10, 15), files=2, insertions=20, deletions=30),
            ],
            tz=TZ,
        )
        self.assertEqual(digest.commit_count, 2)
        self.assertEqual(digest.file_count, 5)
        self.assertEqual(digest.insertions, 120)
        self.assertEqual(digest.deletions, 35)

    def test_active_minutes_span_first_to_last_commit(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[make_commit(1, moment(10, 9)), make_commit(2, moment(10, 10, 45))],
            tz=TZ,
        )
        self.assertEqual(digest.active_minutes, 105)
        self.assertEqual(digest.first_commit_at.hour, 9)
        self.assertEqual(digest.last_commit_at.hour, 10)

    def test_single_commit_has_zero_span(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10), commits=[make_commit(1, moment(10))], tz=TZ
        )
        self.assertEqual(digest.active_minutes, 0)

    def test_empty_day_has_no_span(self) -> None:
        digest = build_day_digest(date(2026, 9, 10), commits=[], tz=TZ)
        self.assertIsNone(digest.active_minutes)
        self.assertIsNone(digest.first_commit_at)
        self.assertTrue(digest.is_empty)


class BugTests(unittest.TestCase):
    def test_bugs_are_filtered_by_the_same_day(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[],
            bugs=[
                make_bug(1, datetime(2026, 9, 10, 3, 0, tzinfo=UTC)),  # 东八区 11:00
                make_bug(2, datetime(2026, 9, 10, 20, 0, tzinfo=UTC)),  # 东八区次日 04:00
            ],
            tz=TZ,
        )
        self.assertEqual([item.id for item in digest.bugs], [1])
        self.assertEqual(digest.bugs[0].status, "open")
        self.assertFalse(digest.is_empty)

    def test_bug_only_day_has_no_commit_draft(self) -> None:
        """只有 Bug、没有提交：不给草稿文本，免得写出一份空内容。"""

        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[],
            bugs=[make_bug(1, datetime(2026, 9, 10, 3, 0, tzinfo=UTC))],
            tz=TZ,
        )
        self.assertEqual(digest.bug_count, 1)
        self.assertEqual(digest.draft_text, "")


class DraftTextTests(unittest.TestCase):
    def test_draft_lists_commits_with_time_and_hash(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[
                make_commit(1, moment(10, 9, 12), "feat: 完成 Git 扫描器"),
                make_commit(2, moment(10, 14, 3), "fix: 中文乱码"),
            ],
            tz=TZ,
        )
        self.assertEqual(
            digest.draft_text.splitlines(),
            [
                f"- 09:12 feat: 完成 Git 扫描器（{1:07d}）",
                f"- 14:03 fix: 中文乱码（{2:07d}）",
            ],
        )

    def test_draft_mentions_the_days_bugs(self) -> None:
        digest = build_day_digest(
            date(2026, 9, 10),
            commits=[make_commit(1, moment(10))],
            bugs=[
                make_bug(1, datetime(2026, 9, 10, 3, 0, tzinfo=UTC), "选目录后闪退"),
                make_bug(2, datetime(2026, 9, 10, 4, 0, tzinfo=UTC), "端口被占用"),
            ],
            tz=TZ,
        )
        self.assertIn("期间处理的问题：选目录后闪退、端口被占用", digest.draft_text)

    def test_draft_is_empty_without_commits(self) -> None:
        digest = build_day_digest(date(2026, 9, 10), commits=[], tz=TZ)
        self.assertEqual(digest.draft_text, "")


class RunnerTests(unittest.TestCase):
    """编排层：项目不存在要报错，未扫描和没干活要分得清。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = DevLogDB(self.root / "digest.db")
        self.project_id = self.db.register_project("demo", self.root)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_unscanned_project_is_flagged_not_silently_empty(self) -> None:
        digest = runner.cmd_day_digest(
            self.db, self.project_id, date(2026, 9, 10), tz=TZ
        )
        self.assertFalse(digest.has_cached_commits)
        self.assertTrue(digest.is_empty)

    def test_scanned_project_reports_the_day(self) -> None:
        self.db.save_events(
            self.project_id,
            [make_commit(1, moment(10, 9)), make_commit(2, moment(9, 9))],
        )
        digest = runner.cmd_day_digest(
            self.db, self.project_id, date(2026, 9, 10), tz=TZ
        )
        self.assertTrue(digest.has_cached_commits)
        self.assertEqual(digest.commit_count, 1)

    def test_digest_carries_the_saved_note(self) -> None:
        self.db.upsert_daily_note(
            self.project_id,
            DailyNote(note_date=date(2026, 9, 10), summary="写了扫描器"),
        )
        digest = runner.cmd_day_digest(
            self.db, self.project_id, date(2026, 9, 10), tz=TZ
        )
        self.assertTrue(digest.has_note)
        self.assertEqual(digest.note.note.summary, "写了扫描器")

    def test_unknown_project_raises(self) -> None:
        with self.assertRaises(Exception):
            runner.cmd_day_digest(self.db, 999, date(2026, 9, 10), tz=TZ)


if __name__ == "__main__":
    unittest.main()
