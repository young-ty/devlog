"""模块 10 测试：记忆层存储（每日笔记、Bug、批注）。

每个测试都在临时目录下使用一次性数据库，绝不触碰 ~/.devlog/ 中的真实数据。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from devlog.core.capture.models import (
    AnnotationKind,
    BugRecord,
    BugStatus,
    CommitAnnotation,
    DailyNote,
)
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.storage import database as database_module
from devlog.core.storage.database import DatabaseError, DevLogDB


def register_project(db: DevLogDB, name: str = "demo") -> int:
    return db.register_project(name, f"D:/work/{name}")


def sample_bug(**overrides: object) -> BugRecord:
    values: dict[str, object] = {
        "title": "接口返回 500",
        "error_text": "Traceback ... KeyError: 'token'",
        "environment": "Windows 11, Python 3.12",
        "git_head": "abc1234 (abc1234abcd)",
        "git_status": "2 files modified",
    }
    values.update(overrides)
    return BugRecord(**values)


class DevLogDBMemoryLayerBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = DevLogDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()


class DailyNoteTests(DevLogDBMemoryLayerBase):
    def test_upsert_creates_then_updates_single_row(self) -> None:
        project_id = register_project(self.db)
        first_id = self.db.upsert_daily_note(
            project_id,
            DailyNote(date(2026, 9, 1), summary="上午写扫描", issues="遇到编码问题"),
        )
        second_id = self.db.upsert_daily_note(
            project_id,
            DailyNote(date(2026, 9, 1), summary="写完了", plan="明天写测试"),
        )

        self.assertEqual(first_id, second_id)
        loaded = self.db.get_daily_note(project_id, date(2026, 9, 1))
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.note.summary, "写完了")
        self.assertEqual(loaded.note.plan, "明天写测试")
        self.assertEqual(
            len(self.db.list_daily_notes(project_id)),
            1,
        )

    def test_list_newest_first_and_date_range(self) -> None:
        project_id = register_project(self.db)
        self.db.upsert_daily_note(
            project_id,
            DailyNote(date(2026, 9, 1), summary="第一天"),
        )
        self.db.upsert_daily_note(
            project_id,
            DailyNote(date(2026, 9, 3), summary="第三天"),
        )

        all_notes = self.db.list_daily_notes(project_id)
        self.assertEqual(
            [item.note.note_date for item in all_notes],
            [date(2026, 9, 3), date(2026, 9, 1)],
        )
        recent = self.db.list_daily_notes(
            project_id, since=date(2026, 9, 2), until=date(2026, 9, 30)
        )
        self.assertEqual(
            [item.note.note_date for item in recent],
            [date(2026, 9, 3)],
        )

    def test_same_date_allowed_for_different_projects(self) -> None:
        first = register_project(self.db, "one")
        second = register_project(self.db, "two")
        self.db.upsert_daily_note(first, DailyNote(date(2026, 9, 1)))
        self.db.upsert_daily_note(second, DailyNote(date(2026, 9, 1)))

        self.assertEqual(len(self.db.list_daily_notes(first)), 1)
        self.assertEqual(len(self.db.list_daily_notes(second)), 1)

    def test_get_missing_note_returns_none(self) -> None:
        project_id = register_project(self.db)
        self.assertIsNone(self.db.get_daily_note(project_id, date(2026, 9, 1)))


class BugRecordTests(DevLogDBMemoryLayerBase):
    def test_create_and_load_roundtrip(self) -> None:
        project_id = register_project(self.db)
        bug_id = self.db.create_bug_record(project_id, sample_bug())

        stored = self.db.get_bug_record(bug_id)
        self.assertEqual(stored.project_id, project_id)
        self.assertEqual(stored.bug.title, "接口返回 500")
        self.assertEqual(stored.bug.status, BugStatus.OPEN)
        self.assertEqual(stored.bug.title_source, "manual")
        self.assertEqual(stored.bug.error_text, "Traceback ... KeyError: 'token'")

    def test_list_newest_first_and_status_filter(self) -> None:
        project_id = register_project(self.db)
        open_id = self.db.create_bug_record(project_id, sample_bug(title="open bug"))
        resolved_id = self.db.create_bug_record(
            project_id,
            sample_bug(title="resolved bug", status=BugStatus.RESOLVED),
        )

        all_items = self.db.list_bug_records(project_id)
        self.assertEqual([item.id for item in all_items], [resolved_id, open_id])
        open_items = self.db.list_bug_records(project_id, status=BugStatus.OPEN)
        self.assertEqual([item.id for item in open_items], [open_id])

    def test_status_flow_updates_annotations_only(self) -> None:
        project_id = register_project(self.db)
        bug_id = self.db.create_bug_record(project_id, sample_bug())

        self.assertTrue(
            self.db.update_bug_record(
                bug_id,
                root_cause="缺少 token 字段",
                status=BugStatus.ROOT_CAUSE_FOUND,
            )
        )
        self.assertTrue(
            self.db.update_bug_record(
                bug_id,
                solution="请求前补上 token",
                status=BugStatus.RESOLVED,
            )
        )
        stored = self.db.get_bug_record(bug_id)
        self.assertEqual(stored.bug.status, BugStatus.RESOLVED)
        self.assertEqual(stored.bug.root_cause, "缺少 token 字段")
        self.assertEqual(stored.bug.solution, "请求前补上 token")
        self.assertEqual(stored.bug.environment, sample_bug().environment)

    def test_update_rejects_unknown_values(self) -> None:
        project_id = register_project(self.db)
        bug_id = self.db.create_bug_record(project_id, sample_bug())

        with self.assertRaises(ValueError):
            self.db.update_bug_record(bug_id, status="mystery")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.db.update_bug_record(bug_id, title_source="voice")

    def test_update_with_no_fields_raises(self) -> None:
        project_id = register_project(self.db)
        bug_id = self.db.create_bug_record(project_id, sample_bug())
        with self.assertRaises(ValueError):
            self.db.update_bug_record(bug_id)

    def test_delete_bug_record(self) -> None:
        project_id = register_project(self.db)
        bug_id = self.db.create_bug_record(project_id, sample_bug())

        self.assertTrue(self.db.delete_bug_record(bug_id))
        self.assertFalse(self.db.delete_bug_record(bug_id))
        with self.assertRaises(DatabaseError):
            self.db.get_bug_record(bug_id)


class CommitAnnotationTests(DevLogDBMemoryLayerBase):
    def test_add_and_list_by_commit(self) -> None:
        project_id = register_project(self.db)
        commit_hash = f"{1:040d}"
        self.db.save_events(project_id, self._event(commit_hash))
        note_id = self.db.add_commit_annotation(
            project_id,
            CommitAnnotation(commit_hash, kind=AnnotationKind.NOTE, body="踩了个坑"),
        )
        decision_id = self.db.add_commit_annotation(
            project_id,
            CommitAnnotation(
                commit_hash,
                kind=AnnotationKind.DECISION,
                body="选 B 因为兼容性更好",
            ),
        )

        by_commit = self.db.list_commit_annotations(project_id, commit_hash)
        self.assertEqual({item.id for item in by_commit}, {note_id, decision_id})
        kinds = {item.annotation.kind for item in by_commit}
        self.assertEqual(kinds, {AnnotationKind.NOTE, AnnotationKind.DECISION})

    def test_requires_cached_commit(self) -> None:
        project_id = register_project(self.db)
        with self.assertRaises(DatabaseError):
            self.db.add_commit_annotation(
                project_id,
                CommitAnnotation(f"{9:040d}", body="挂不上"),
            )

    def test_orphan_detection_after_commit_disappears(self) -> None:
        project_id = register_project(self.db)
        other_project = register_project(self.db, "other")
        commit_hash = f"{1:040d}"
        self.db.save_events(project_id, self._event(commit_hash))
        # 同一 hash 也存在于另一个项目：这不能“救回”孤儿批注，
        # 因为 commit 是按项目隔离的。
        self.db.save_events(other_project, self._event(commit_hash))
        annotation_id = self.db.add_commit_annotation(
            project_id,
            CommitAnnotation(commit_hash, body="批注"),
        )
        self.assertEqual(self.db.list_orphan_commit_annotations(project_id), [])

        self.db.clear_events(project_id)
        orphans = self.db.list_orphan_commit_annotations(project_id)
        self.assertEqual([item.id for item in orphans], [annotation_id])

    def test_update_and_delete_annotation(self) -> None:
        project_id = register_project(self.db)
        commit_hash = f"{1:040d}"
        self.db.save_events(project_id, self._event(commit_hash))
        annotation_id = self.db.add_commit_annotation(
            project_id,
            CommitAnnotation(commit_hash, kind=AnnotationKind.NOTE, body="旧的"),
        )

        self.assertTrue(
            self.db.update_commit_annotation(
                annotation_id,
                kind=AnnotationKind.DECISION,
                body="改成决策",
            )
        )
        stored = self.db.list_commit_annotations(project_id)[0]
        self.assertEqual(stored.annotation.kind, AnnotationKind.DECISION)
        self.assertEqual(stored.annotation.body, "改成决策")

        self.assertTrue(self.db.delete_commit_annotation(annotation_id))
        self.assertFalse(self.db.delete_commit_annotation(annotation_id))

    @staticmethod
    def _event(commit_hash: str):
        return [
            CommitEvent(
                hash=commit_hash,
                short_hash=commit_hash[:7],
                author_name="dev",
                author_email="dev@example.com",
                committed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                message_subject="feat: sample",
                files_changed=1,
                insertions=1,
                deletions=0,
                parents_count=0,
                noise_type=NoiseType.NONE,
            )
        ]


class CaptureSchemaMigrationTests(unittest.TestCase):
    def test_v3_database_upgrades_to_v4_and_keeps_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v3.db"
            conn = database_module.sqlite3.connect(str(path))
            for statements in (
                database_module._SCHEMA_V1_STATEMENTS,
                database_module._SCHEMA_V2_STATEMENTS,
                database_module._SCHEMA_V3_STATEMENTS,
            ):
                for statement in statements:
                    conn.execute(statement)
            conn.execute(
                "INSERT INTO projects (name, path, created_at) VALUES (?, ?, ?)",
                ("demo", str(Path("D:/work/demo").resolve()), "2026-01-01T00:00:00+00:00"),
            )
            conn.execute("PRAGMA user_version = 3")
            conn.commit()
            conn.close()

            upgraded = DevLogDB(path)
            try:
                self.assertEqual(upgraded.schema_version, 6)
                same_id = upgraded.register_project("renamed", "D:/work/demo")
                self.assertEqual(same_id, 1)
                bug_id = upgraded.create_bug_record(
                    1,
                    sample_bug(title="升级后仍可捕获"),
                )
                self.assertGreater(bug_id, 0)
                tables = {
                    row[0]
                    for row in upgraded._conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "dev_notes",
                        "bug_records",
                        "commit_annotations",
                        "draft_answers",
                    }
                    <= tables
                )
            finally:
                upgraded.close()


if __name__ == "__main__":
    unittest.main()
