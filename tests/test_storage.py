"""Module 2 tests: SQLite state store.

Every test uses a throwaway database file under a temp directory so real
user data under ~/.devlog/ is never touched.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.storage.database import DevLogDB


TZ = timezone(timedelta(hours=8))
SCHEMA_VERSION = 1


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


if __name__ == "__main__":
    unittest.main()
