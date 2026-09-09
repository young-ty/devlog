"""模块 7 测试：基于真实临时仓库的 FastAPI 接口测试。"""

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

from devlog.core.storage.database import DevLogDB
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

            response = client.get("/api/projects/999/notes")
            self.assertEqual(response.status_code, 404)

            response = client.get("/api/projects/999/bugs")
            self.assertEqual(response.status_code, 404)

            response = client.get("/api/projects/999/annotations")
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


class MemoryAPITests(unittest.TestCase):
    """模块 10-2：记忆层 HTTP 接口测试（使用一次性仓库与数据库）。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root)
        self.db_path = Path(self.root) / "memory-api.db"
        commit(self.repo, "login.py", "def login(): ...\n", "feat: add login page", at(1))
        commit(self.repo, "login.py", "def login(): return True\n", "fix: login button", at(2))
        self.app = create_app(self.db_path)

    def tearDown(self) -> None:
        force_remove(self.root)

    def _register_and_scan(self, client: TestClient) -> tuple[int, str]:
        response = client.post("/api/projects", json={"path": str(self.repo)})
        self.assertEqual(response.status_code, 201)
        project_id = response.json()["project_id"]
        response = client.post(f"/api/projects/{project_id}/scan", json={})
        self.assertEqual(response.status_code, 200)
        timeline = client.get(f"/api/projects/{project_id}/timeline")
        self.assertEqual(timeline.status_code, 200)
        commit_hash = timeline.json()["commits"][0]["hash"]
        return project_id, commit_hash

    def test_daily_notes_upsert_and_list(self) -> None:
        with TestClient(self.app) as client:
            project_id, _ = self._register_and_scan(client)
            url = f"/api/projects/{project_id}/notes"

            first = client.post(
                url,
                json={"note_date": "2026-09-01", "summary": "上午写完扫描器"},
            )
            self.assertEqual(first.status_code, 200)
            note_id = first.json()["id"]

            second = client.post(
                url,
                json={
                    "note_date": "2026-09-01",
                    "summary": "晚上补上 Bug 捕获",
                    "plan": "明天做前端",
                },
            )
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["id"], note_id)
            self.assertEqual(second.json()["summary"], "晚上补上 Bug 捕获")

            single = client.get(url, params={"note_date": "2026-09-01"})
            self.assertEqual(single.status_code, 200)
            self.assertEqual(len(single.json()), 1)

            client.post(
                url,
                json={"note_date": "2026-09-02", "summary": "第二天"},
            )
            all_notes = client.get(url)
            self.assertEqual(all_notes.status_code, 200)
            self.assertEqual(
                [item["note_date"] for item in all_notes.json()],
                ["2026-09-02", "2026-09-01"],
            )

    def test_bug_capture_patch_and_delete(self) -> None:
        with TestClient(self.app) as client:
            project_id, _ = self._register_and_scan(client)
            url = f"/api/projects/{project_id}/bugs"

            response = client.post(
                url,
                json={"error_text": "ERROR: token 字段缺失"},
            )
            self.assertEqual(response.status_code, 201)
            bug = response.json()
            bug_id = bug["id"]
            self.assertEqual(bug["title"], "ERROR: token 字段缺失")
            self.assertEqual(bug["title_source"], "manual")
            self.assertEqual(bug["status"], "open")
            self.assertTrue(bug["environment"])
            self.assertTrue(bug["git_head"])
            self.assertEqual(bug["git_status"], "clean")

            listed = client.get(url)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["id"] for item in listed.json()], [bug_id])

            filtered = client.get(url, params={"status": "open"})
            self.assertEqual(len(filtered.json()), 1)

            updated = client.patch(
                f"/api/bugs/{bug_id}",
                json={
                    "root_cause": "没带 token",
                    "solution": "请求头补 token",
                    "status": "resolved",
                },
            )
            self.assertEqual(updated.status_code, 200)
            body = updated.json()
            self.assertEqual(body["status"], "resolved")
            self.assertEqual(body["root_cause"], "没带 token")
            self.assertEqual(body["solution"], "请求头补 token")
            # 现场快照字段不能被更新覆盖
            self.assertEqual(body["environment"], bug["environment"])
            self.assertEqual(body["git_head"], bug["git_head"])

            invalid_status = client.patch(
                f"/api/bugs/{bug_id}", json={"status": "mystery"}
            )
            self.assertEqual(invalid_status.status_code, 400)

            empty = client.patch(f"/api/bugs/{bug_id}", json={})
            self.assertEqual(empty.status_code, 400)

            deleted = client.delete(f"/api/bugs/{bug_id}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json(), {"deleted": True})

            again = client.delete(f"/api/bugs/{bug_id}")
            self.assertEqual(again.json(), {"deleted": False})

    def test_commit_annotations_lifecycle_and_orphan(self) -> None:
        with TestClient(self.app) as client:
            project_id, commit_hash = self._register_and_scan(client)
            list_url = f"/api/projects/{project_id}/annotations"
            unknown_hash = "f" * 40

            response = client.post(
                f"/api/projects/{project_id}/commits/{commit_hash}/annotations",
                json={"kind": "decision", "body": "选 PostgreSQL 便于全文检索"},
            )
            self.assertEqual(response.status_code, 201)
            annotation = response.json()
            annotation_id = annotation["id"]
            self.assertEqual(annotation["commit_hash"], commit_hash)
            self.assertEqual(annotation["kind"], "decision")

            missing = client.post(
                f"/api/projects/{project_id}/commits/{unknown_hash}/annotations",
                json={"kind": "note", "body": "挂不上"},
            )
            self.assertEqual(missing.status_code, 404)

            listed = client.get(list_url)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(
                [item["id"] for item in listed.json()],
                [annotation_id],
            )

            updated = client.patch(
                f"/api/annotations/{annotation_id}",
                json={"body": "后来改成了 SQLite"},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["body"], "后来改成了 SQLite")

            empty = client.patch(f"/api/annotations/{annotation_id}", json={})
            self.assertEqual(empty.status_code, 400)

            deleted = client.delete(f"/api/annotations/{annotation_id}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json(), {"deleted": True})

            # 再加一条，然后清空 commit 缓存，让它变成“孤儿”批注
            client.post(
                f"/api/projects/{project_id}/commits/{commit_hash}/annotations",
                json={"kind": "note", "body": "这条会变成孤儿"},
            )
            db = DevLogDB(self.db_path)
            try:
                db.clear_events(project_id)
            finally:
                db.close()

            orphaned = client.get(list_url, params={"orphan": True})
            self.assertEqual(orphaned.status_code, 200)
            orphan_list = orphaned.json()
            self.assertEqual(len(orphan_list), 1)
            self.assertEqual(orphan_list[0]["body"], "这条会变成孤儿")


if __name__ == "__main__":
    unittest.main()
