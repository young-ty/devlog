"""模块 2 测试：SQLite 状态存储。

每个测试都在临时目录下使用一次性数据库文件，绝不触碰 ~/.devlog/
中的真实用户数据。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from devlog.core.capture.models import DailyNote
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.review.models import (
    SECTION_DECISIONS,
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
)
from devlog.core.storage import database as database_module
from devlog.core.storage.database import DatabaseError, DevLogDB


TZ = timezone(timedelta(hours=8))
SCHEMA_VERSION = 4


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 9, 0, tzinfo=TZ)


def make_event(number: int, day: int, noise: NoiseType = NoiseType.NONE) -> CommitEvent:
    return CommitEvent(
        hash=f"{number:040d}",
        short_hash=f"{number:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=at(day),
        message_subject="feat: sample",
        files_changed=1,
        insertions=1,
        deletions=0,
        parents_count=0,
        noise_type=noise,
    )


def make_v1_database(path: Path) -> None:
    """创建一个只知道 schema 版本 1 的数据库。"""

    conn = database_module.sqlite3.connect(str(path))
    for statement in database_module._SCHEMA_V1_STATEMENTS:
        conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def make_sample_draft() -> ReviewDraft:
    return ReviewDraft(
        project_name="demo",
        range_start=at(1),
        range_end=at(3),
        claims=[
            ReviewClaim(
                section=SECTION_OVERVIEW,
                text="共 2 次有效提交。",
                sources=(f"{1:040d}", f"{2:040d}"),
                status=ClaimStatus.FACT,
            ),
            ReviewClaim(
                section=SECTION_TIMELINE,
                text="主题「login」：实现了登录功能。",
                sources=(f"{1:040d}",),
                status=ClaimStatus.AI_PENDING,
            ),
        ],
        questions=["这里发生了什么？", "下一步计划是什么？"],
    )


class DevLogDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = DevLogDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_schema_version_is_created(self) -> None:
        self.assertEqual(self.db.schema_version, SCHEMA_VERSION)

    def test_register_project_and_duplicate_register(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        self.assertIsInstance(project_id, int)
        self.assertGreater(project_id, 0)

        again = self.db.register_project("demo-again", "D:/work/demo")
        self.assertEqual(again, project_id)

    def test_list_and_get_project(self) -> None:
        self.assertEqual(self.db.list_projects(), [])

        project_id = self.db.register_project("demo", "D:/work/demo")
        projects = self.db.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].project_id, project_id)
        self.assertEqual(projects[0].name, "demo")
        self.assertEqual(projects[0].path, str(Path("D:/work/demo").resolve()))

        loaded = self.db.get_project(project_id)
        self.assertEqual(loaded.name, "demo")
        with self.assertRaises(DatabaseError):
            self.db.get_project(999)

    def test_save_and_list_roundtrip(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        events = [make_event(1, 1), make_event(2, 2), make_event(3, 3)]

        inserted = self.db.save_events(project_id, events)
        self.assertEqual(inserted, 3)

        loaded = self.db.list_events(project_id, include_noise=True)
        self.assertEqual(loaded, events)
        self.assertEqual([e.committed_at for e in loaded], [at(1), at(2), at(3)])

    def test_save_twice_is_idempotent(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        events = [make_event(1, 1)]

        first = self.db.save_events(project_id, events)
        second = self.db.save_events(project_id, events)
        loaded = self.db.list_events(project_id, include_noise=True)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(len(loaded), 1)

    def test_noise_events_hidden_by_default(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        events = [
            make_event(1, 1),
            make_event(2, 2, noise=NoiseType.WIP),
            make_event(3, 3, noise=NoiseType.MERGE),
        ]
        self.db.save_events(project_id, events)

        clean = self.db.list_events(project_id)
        all_events = self.db.list_events(project_id, include_noise=True)

        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0].hash, f"{1:040d}")
        self.assertEqual(len(all_events), 3)

    def test_time_filter(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        self.db.save_events(
            project_id, [make_event(1, 1), make_event(2, 2), make_event(3, 3)]
        )

        loaded = self.db.list_events(
            project_id, since=at(2), until=at(2), include_noise=True
        )
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].hash, f"{2:040d}")

    def test_same_hash_allowed_in_different_projects(self) -> None:
        first = self.db.register_project("one", "D:/work/one")
        second = self.db.register_project("two", "D:/work/two")
        event = make_event(7, 1)

        self.db.save_events(first, [event])
        self.db.save_events(second, [event])

        self.assertEqual(len(self.db.list_events(first, include_noise=True)), 1)
        self.assertEqual(len(self.db.list_events(second, include_noise=True)), 1)

    def test_scan_cursor_update_and_read(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        self.assertIsNone(self.db.get_scan_cursor(project_id))

        self.db.update_scan_cursor(project_id, "abc" * 13 + "a")
        self.assertEqual(self.db.get_scan_cursor(project_id), "abc" * 13 + "a")

    def test_clear_events_keeps_project(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        self.db.save_events(project_id, [make_event(1, 1), make_event(2, 2)])
        self.db.update_scan_cursor(project_id, "a" * 40)

        removed = self.db.clear_events(project_id)
        self.assertEqual(removed, 2)
        self.assertEqual(self.db.list_events(project_id, include_noise=True), [])
        self.assertEqual(self.db.get_scan_cursor(project_id), "a" * 40)

    def test_v1_database_upgrades_to_latest_and_keeps_data(self) -> None:
        v1_path = Path(self._tmp.name) / "v1.db"
        make_v1_database(v1_path)

        old_conn = database_module.sqlite3.connect(str(v1_path))
        old_conn.execute(
            "INSERT INTO projects (name, path, created_at) VALUES (?, ?, ?)",
            ("demo", str(Path("D:/work/demo").resolve()), "2026-01-01T00:00:00+00:00"),
        )
        old_conn.commit()
        old_conn.close()

        upgraded = DevLogDB(v1_path)
        try:
            self.assertEqual(upgraded.schema_version, SCHEMA_VERSION)
            same_id = upgraded.register_project("renamed", "D:/work/demo")
            self.assertEqual(same_id, 1)
            draft_id = upgraded.save_review_draft(1, make_sample_draft())
            self.assertGreater(draft_id, 0)
            inserted = upgraded.save_commit_translations(
                1, {f"{1:040d}": "新增登录页面"}
            )
            self.assertEqual(inserted, 1)
            note_id = upgraded.upsert_daily_note(
                1,
                DailyNote(
                    note_date=date(2026, 9, 1),
                    summary="迁移后仍可写日志",
                ),
            )
            self.assertGreater(note_id, 0)
        finally:
            upgraded.close()

    def test_commit_translation_cache_roundtrip(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        first_hash = f"{1:040d}"
        second_hash = f"{2:040d}"

        inserted = self.db.save_commit_translations(
            project_id,
            {first_hash: "新增登录页面", second_hash: "修复登录按钮"},
        )
        self.assertEqual(inserted, 2)

        again = self.db.save_commit_translations(
            project_id,
            {first_hash: "不应覆盖旧翻译"},
        )
        self.assertEqual(again, 0)

        all_items = self.db.list_commit_translations(project_id)
        self.assertEqual(all_items[first_hash], "新增登录页面")
        self.assertEqual(all_items[second_hash], "修复登录按钮")

        filtered = self.db.list_commit_translations(
            project_id, hashes=[first_hash]
        )
        self.assertEqual(set(filtered), {first_hash})

    def test_save_and_load_review_draft_roundtrip(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        draft = make_sample_draft()

        draft_id = self.db.save_review_draft(project_id, draft)
        record = self.db.load_review_draft(draft_id)

        self.assertEqual(record.project_name, "demo")
        self.assertEqual(record.draft.range_start, at(1))
        self.assertEqual(record.draft.range_end, at(3))
        self.assertEqual(record.draft.questions, draft.questions)
        self.assertEqual(len(record.draft.claims), 2)
        self.assertEqual(record.draft.claims[0].status, ClaimStatus.FACT)
        self.assertEqual(record.draft.claims[1].status, ClaimStatus.AI_PENDING)
        self.assertGreater(len(record.draft.claims[1].sources), 0)

        summaries = self.db.list_review_drafts(project_id)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].draft_id, draft_id)
        self.assertEqual(summaries[0].total_claims, 2)
        self.assertEqual(summaries[0].ai_pending_claims, 1)
        self.assertEqual(summaries[0].confirmed_claims, 0)

    def test_confirm_claim_transitions_and_keeps_facts(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        draft_id = self.db.save_review_draft(project_id, make_sample_draft())
        record = self.db.load_review_draft(draft_id)

        # 从存储记录包装对象中取回论断 id。
        fact_id = next(
            item.id for item in record.stored_claims if item.claim.status == ClaimStatus.FACT
        )
        pending_id = next(
            item.id
            for item in record.stored_claims
            if item.claim.status == ClaimStatus.AI_PENDING
        )

        self.assertFalse(self.db.confirm_review_claim(draft_id, fact_id))
        self.assertTrue(
            self.db.confirm_review_claim(draft_id, pending_id, note="人工复核通过")
        )

        reloaded = self.db.load_review_draft(draft_id)
        status_by_id = {
            item.id: (item.claim.status, item.claim.user_note)
            for item in reloaded.stored_claims
        }
        self.assertEqual(status_by_id[fact_id][0], ClaimStatus.FACT)
        self.assertEqual(status_by_id[pending_id][0], ClaimStatus.CONFIRMED)
        self.assertEqual(status_by_id[pending_id][1], "人工复核通过")

    def test_confirm_all_ai_claims(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        draft_id = self.db.save_review_draft(project_id, make_sample_draft())

        changed = self.db.confirm_all_ai_claims(draft_id)
        record = self.db.load_review_draft(draft_id)

        self.assertEqual(changed, 1)
        statuses = [item.claim.status for item in record.stored_claims]
        self.assertEqual(statuses, [ClaimStatus.FACT, ClaimStatus.CONFIRMED])

    def test_mark_draft_exported(self) -> None:
        project_id = self.db.register_project("demo", "D:/work/demo")
        draft_id = self.db.save_review_draft(project_id, make_sample_draft())

        self.db.mark_draft_exported(draft_id, "D:/work/demo/docs/review.md")
        record = self.db.load_review_draft(draft_id)

        self.assertIsNotNone(record.exported_path)
        self.assertIn("review.md", record.exported_path or "")


if __name__ == "__main__":
    unittest.main()
