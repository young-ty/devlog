"""Module 1 tests: Git repository scanning and event normalization.

Each test builds a real throwaway git repository so behavior stays
reproducible and independent of the working project.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devlog.core.git_source.models import NoiseType
from devlog.core.git_source.scanner import GitSourceError, scan_repository


TZ = timezone(timedelta(hours=8))


def force_remove(path: Path) -> None:
    """Remove a temp git repo even when git marked object files read-only."""

    def onerror(func, item, _info):
        os.chmod(item, stat.S_IWRITE)
        func(item)

    shutil.rmtree(path, onerror=onerror)


def at(day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=TZ)


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=full_env,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise AssertionError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def make_repo(root: Path, name: str = "repo") -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "user.name", "dev")
    run_git(repo, "config", "user.email", "dev@example.com")
    return repo


def commit(repo: Path, filename: str, content: str, message: str, when: datetime) -> None:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    run_git(repo, "add", "--", filename)
    iso = when.isoformat()
    run_git(
        repo,
        "commit",
        "-q",
        "-m",
        message,
        env={"GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso},
    )


class ScanRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root)

    def tearDown(self) -> None:
        force_remove(self.root)

    def test_empty_repo_returns_empty_list(self) -> None:
        self.assertEqual(scan_repository(self.repo), [])

    def test_single_commit_fields(self) -> None:
        commit(self.repo, "main.py", "print('hello')\n", "feat: add greeting", at(1))

        events = scan_repository(self.repo)
        self.assertEqual(len(events), 1)
        event = events[0]

        self.assertEqual(len(event.hash), 40)
        self.assertEqual(event.short_hash, event.hash[:7])
        self.assertEqual(event.author_name, "dev")
        self.assertEqual(event.author_email, "dev@example.com")
        self.assertEqual(event.message_subject, "feat: add greeting")
        self.assertEqual(event.committed_at, at(1))
        self.assertEqual(event.files_changed, 1)
        self.assertEqual(event.insertions, 1)
        self.assertEqual(event.deletions, 0)
        self.assertEqual(event.parents_count, 0)
        self.assertEqual(event.noise_type, NoiseType.NONE)

        payload = event.to_dict()
        self.assertEqual(payload["short_hash"], event.short_hash)
        self.assertEqual(payload["noise_type"], "none")

    def test_chronological_order_and_multiple_files(self) -> None:
        commit(self.repo, "one.py", "a = 1\n", "feat: one", at(1))
        commit(self.repo, "two.py", "b = 2\n", "feat: two", at(2, 10))
        commit(self.repo, "three.py", "c = 3\n", "fix: three", at(3, 11))

        events = scan_repository(self.repo)
        self.assertEqual([e.message_subject for e in events], ["feat: one", "feat: two", "fix: three"])
        self.assertEqual([e.files_changed for e in events], [1, 1, 1])

    def test_wip_and_chore_are_marked_as_noise(self) -> None:
        commit(self.repo, "draft.py", "x = 1\n", "wip: draft notes", at(1))
        commit(self.repo, "dep.txt", "fastapi==1.0\n", "chore: bump dependency", at(2))
        commit(self.repo, "real.py", "y = 2\n", "feat: real work", at(3))

        events = scan_repository(self.repo)
        self.assertEqual([e.noise_type for e in events], [NoiseType.WIP, NoiseType.CHORE, NoiseType.NONE])

    def test_merge_commit_is_marked_as_merge(self) -> None:
        commit(self.repo, "base.txt", "base\n", "feat: base work", at(1))

        run_git(self.repo, "checkout", "-q", "-b", "feature")
        commit(self.repo, "feature.txt", "feature\n", "feat: feature work", at(2, 10))

        run_git(self.repo, "checkout", "-q", "main")
        commit(self.repo, "main.txt", "main\n", "feat: main work", at(3, 10))

        merge_when = at(4, 10)
        run_git(
            self.repo,
            "merge",
            "--no-ff",
            "-q",
            "feature",
            "-m",
            "Merge branch 'feature'",
            env={
                "GIT_AUTHOR_DATE": merge_when.isoformat(),
                "GIT_COMMITTER_DATE": merge_when.isoformat(),
            },
        )

        events = scan_repository(self.repo)
        merge_events = [e for e in events if e.message_subject.startswith("Merge")]
        self.assertEqual(len(merge_events), 1)
        self.assertEqual(merge_events[0].parents_count, 2)
        self.assertEqual(merge_events[0].noise_type, NoiseType.MERGE)

    def test_revert_commit_is_marked_as_revert(self) -> None:
        commit(self.repo, "config.py", "KEY = 'v1'\n", "feat: add config", at(1))
        revert_when = at(2, 10)
        run_git(
            self.repo,
            "revert",
            "--no-edit",
            "HEAD",
            env={
                "GIT_AUTHOR_DATE": revert_when.isoformat(),
                "GIT_COMMITTER_DATE": revert_when.isoformat(),
            },
        )

        events = scan_repository(self.repo)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].noise_type, NoiseType.REVERT)
        self.assertTrue(events[1].message_subject.startswith("Revert"))

    def test_since_until_filter(self) -> None:
        commit(self.repo, "a.txt", "a\n", "feat: first", at(1, 10))
        commit(self.repo, "b.txt", "b\n", "feat: second", at(2, 10))
        commit(self.repo, "c.txt", "c\n", "feat: third", at(3, 10))

        events = scan_repository(self.repo, since=at(2, 0), until=at(2, 23, 59))
        self.assertEqual([e.message_subject for e in events], ["feat: second"])

    def test_scan_is_idempotent(self) -> None:
        commit(self.repo, "a.txt", "a\n", "feat: a", at(1))
        commit(self.repo, "b.txt", "b\n", "feat: b", at(2))

        first = scan_repository(self.repo)
        second = scan_repository(self.repo)
        self.assertEqual(first, second)

    def test_non_git_directory_raises_friendly_error(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(GitSourceError, "failed to read git repository"):
            scan_repository(plain)

    def test_missing_path_raises_friendly_error(self) -> None:
        missing = self.root / "does-not-exist"
        with self.assertRaisesRegex(GitSourceError, "path does not exist"):
            scan_repository(missing)


if __name__ == "__main__":
    unittest.main()
