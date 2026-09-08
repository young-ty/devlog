"""Module 7 tests: FastAPI endpoints over a real throwaway repository."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from devlog.server.app import create_app


TZ = timezone(timedelta(hours=8))


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 9, 0, tzinfo=TZ)


def force_remove(path: Path) -> None:
    def onerror(func, item, _info):
        os.chmod(item, stat.S_IWRITE)
        func(item)

    shutil.rmtree(path, onerror=onerror)


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
    run_git(
        repo,
        "commit",
        "-q",
        "-m",
        message,
        env={
            "GIT_AUTHOR_DATE": when.isoformat(),
            "GIT_COMMITTER_DATE": when.isoformat(),
        },
    )


class APIFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root)
        self.db_path = Path(self.root) / "api.db"
        commit(self.repo, "login.py", "def login(): ...\n", "feat: add login page", at(1))
        commit(self.repo, "login.py", "def login(): return True\n", "fix: login button", at(2))
        self.app = create_app(self.db_path)

    def tearDown(self) -> None:
        force_remove(self.root)

    def test_end_to_end_project_scan_review_confirm_export(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/projects")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

            response = client.post(
                "/api/projects",
                json={"path": str(self.repo), "name": "demo-api"},
            )
            self.assertEqual(response.status_code, 201)
            project_id = response.json()["project_id"]
            self.assertGreater(project_id, 0)

            duplicate = client.post(
                "/api/projects", json={"path": str(self.repo)}
            )
            self.assertEqual(duplicate.status_code, 201)
            self.assertEqual(duplicate.json()["project_id"], project_id)

            response = client.post(
                f"/api/projects/{project_id}/scan", json={}
            )
            self.assertEqual(response.status_code, 200)
            scan = response.json()
            self.assertEqual(scan["total_events"], 2)
            self.assertEqual(scan["inserted_events"], 2)
            self.assertEqual(scan["project_name"], "demo-api")

            response = client.post(
                f"/api/projects/{project_id}/reviews/generate",
                json={"offline": True},
            )
            self.assertEqual(response.status_code, 200)
            generated = response.json()
            draft_id = generated["draft_id"]
            self.assertEqual(generated["offline"], True)
            self.assertEqual(generated["claim_count"], 2)
            self.assertEqual(generated["ai_pending_count"], 0)

            response = client.get(f"/api/projects/{project_id}/reviews")
            self.assertEqual(response.status_code, 200)
            summaries = response.json()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["draft_id"], draft_id)

            response = client.get(f"/api/reviews/{draft_id}")
            self.assertEqual(response.status_code, 200)
            draft = response.json()
            self.assertEqual(len(draft["claims"]), 2)
            self.assertTrue(
                all(claim["status"] == "fact" for claim in draft["claims"])
            )
            self.assertIsInstance(draft["range_start"], str)

            response = client.post(
                f"/api/reviews/{draft_id}/confirm", json={"all": True}
            )
            self.assertEqual(response.status_code, 200)
            confirm = response.json()
            self.assertEqual(confirm["changed"], 0)
            self.assertEqual(confirm["remaining_pending"], 0)

            response = client.post(
                f"/api/reviews/{draft_id}/export", json={}
            )
            self.assertEqual(response.status_code, 200)
            export_path = Path(response.json()["path"])
            self.assertTrue(export_path.exists())
            self.assertEqual(export_path.parent.name, "retrospectives")

    def test_missing_resources_return_404(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/projects/999/reviews")
            self.assertEqual(response.status_code, 404)

            response = client.get("/api/projects/999/timeline")
            self.assertEqual(response.status_code, 404)

            response = client.post(
                "/api/projects/999/translations", json={}
            )
            self.assertEqual(response.status_code, 404)

            response = client.get("/api/reviews/999")
            self.assertEqual(response.status_code, 404)

            response = client.post(
                "/api/projects/999/scan", json={"reset": False}
            )
            self.assertEqual(response.status_code, 404)

    def test_generate_without_scan_returns_400(self) -> None:
        with TestClient(self.app) as client:
            response = client.post(
                "/api/projects",
                json={"path": str(self.repo)},
            )
            project_id = response.json()["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/reviews/generate",
                json={"offline": True},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("scan", response.json()["detail"])

    def test_timeline_returns_commits_themes_and_silence(self) -> None:
        commit(self.repo, "wip.txt", "scratch\n", "wip: scratch notes", at(8))
        commit(
            self.repo,
            "dashboard.py",
            "def dashboard(): ...\n",
            "feat: add dashboard page",
            at(9),
        )

        with TestClient(self.app) as client:
            response = client.post(
                "/api/projects",
                json={"path": str(self.repo)},
            )
            project_id = response.json()["project_id"]
            response = client.post(
                f"/api/projects/{project_id}/scan",
                json={},
            )
            self.assertEqual(response.status_code, 200)

            response = client.get(
                f"/api/projects/{project_id}/timeline"
            )
            self.assertEqual(response.status_code, 200)
            timeline = response.json()

            self.assertEqual(timeline["project_name"], "repo")
            self.assertEqual(len(timeline["commits"]), 4)
            self.assertEqual(len(timeline["themes"]), 2)
            self.assertEqual(len(timeline["silence_periods"]), 1)

            messages = [
                commit_item["message_subject"]
                for commit_item in timeline["commits"]
            ]
            self.assertIn("wip: scratch notes", messages)

            noise_commit = next(
                item
                for item in timeline["commits"]
                if item["message_subject"] == "wip: scratch notes"
            )
            self.assertEqual(noise_commit["noise_type"], "wip")

            login_theme = next(
                theme
                for theme in timeline["themes"]
                if theme["commit_count"] == 2
            )
            self.assertEqual(len(login_theme["commit_hashes"]), 2)

            silence = timeline["silence_periods"][0]
            self.assertGreaterEqual(silence["days"], 3)

    def test_create_project_rejects_non_git_path(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        with TestClient(self.app) as client:
            response = client.post(
                "/api/projects", json={"path": str(plain)}
            )
            self.assertEqual(response.status_code, 400)

    def test_llm_config_reports_safe_settings(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/llm/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("model", body)
        self.assertIn("base_url", body)
        self.assertIsInstance(body["configured"], bool)


if __name__ == "__main__":
    unittest.main()
