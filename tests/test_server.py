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

    def test_guidance_answers_are_saved_and_exported(self) -> None:
        """引导问题要能写、能存，并且导出时落进对应板块。"""

        answer = "踩坑：SQLite 连接跨线程要用 check_same_thread=False。"
        with TestClient(self.app) as client:
            project_id = client.post(
                "/api/projects", json={"path": str(self.repo)}
            ).json()["project_id"]
            client.post(f"/api/projects/{project_id}/scan", json={})
            draft_id = client.post(
                f"/api/projects/{project_id}/reviews/generate",
                json={"offline": True},
            ).json()["draft_id"]

            draft = client.get(f"/api/reviews/{draft_id}").json()
            self.assertEqual(len(draft["questions"]), 3)
            self.assertTrue(
                all(item["answer"] == "" for item in draft["questions"])
            )
            self.assertEqual(
                [item["section"] for item in draft["questions"]],
                ["技术决策记录", "踩坑总结", "遗留与下一步"],
            )

            saved = client.put(
                f"/api/reviews/{draft_id}/answers/2",
                json={"answer": answer},
            )
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["section"], "踩坑总结")
            self.assertEqual(saved.json()["answer"], answer)

            reloaded = client.get(f"/api/reviews/{draft_id}").json()
            self.assertEqual(reloaded["questions"][1]["answer"], answer)
            self.assertEqual(reloaded["questions"][0]["answer"], "")

            out_of_range = client.put(
                f"/api/reviews/{draft_id}/answers/9",
                json={"answer": "越界"},
            )
            self.assertEqual(out_of_range.status_code, 400)

            exported = client.post(
                f"/api/reviews/{draft_id}/export", json={}
            )
            self.assertEqual(exported.status_code, 200)
            text = Path(exported.json()["path"]).read_text(encoding="utf-8")
            lessons = text.split("## 踩坑总结")[1].split("##")[0]
            self.assertIn(answer, lessons)
            self.assertNotIn(answer, text.split("## 待补充的问题")[1])

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
            # 离线模式不调用 AI，可复用资产候选数必须是 0。
            self.assertEqual(generated["asset_count"], 0)

            response = client.get(f"/api/projects/{project_id}/reviews")
            self.assertEqual(response.status_code, 200)
            summaries = response.json()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["draft_id"], draft_id)

            response = client.get(f"/api/reviews/{draft_id}")
            self.assertEqual(response.status_code, 200)
            draft = response.json()
            self.assertEqual(len(draft["claims"]), 2)
            self.assertEqual(draft["generation_mode"], "offline")
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

    def test_review_draft_can_be_deleted(self) -> None:
        with TestClient(self.app) as client:
            project_id = client.post(
                "/api/projects",
                json={"path": str(self.repo), "name": "demo-api"},
            ).json()["project_id"]
            client.post(f"/api/projects/{project_id}/scan", json={})
            draft_id = client.post(
                f"/api/projects/{project_id}/reviews/generate",
                json={"offline": True},
            ).json()["draft_id"]

            summaries = client.get(
                f"/api/projects/{project_id}/reviews"
            ).json()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["generation_mode"], "offline")

            response = client.delete(f"/api/reviews/{draft_id}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["deleted"])

            self.assertEqual(
                client.get(f"/api/projects/{project_id}/reviews").json(), []
            )
            self.assertEqual(
                client.get(f"/api/reviews/{draft_id}").status_code, 404
            )

            # 重复删除要给出 404，而不是假装成功或抛 500。
            repeat = client.delete(f"/api/reviews/{draft_id}")
            self.assertEqual(repeat.status_code, 404)

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


class TimelineEventsAPITests(unittest.TestCase):
    """时间线事件流接口：把四类来源合并成一条排好序的事件流。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root)
        self.db_path = Path(self.root) / "events.db"
        commit(self.repo, "login.py", "def login(): ...\n", "feat: add login page", at(1))
        commit(self.repo, "login.py", "def login(): return True\n", "fix: login button", at(2))
        commit(self.repo, "pay.py", "def pay(): ...\n", "feat: add payment page", at(9))
        self.app = create_app(self.db_path)

    def tearDown(self) -> None:
        force_remove(self.root)

    def prepare(self, client) -> int:
        project_id = client.post(
            "/api/projects", json={"path": str(self.repo)}
        ).json()["project_id"]
        client.post(f"/api/projects/{project_id}/scan", json={})
        return project_id

    def test_events_merge_every_source_in_time_order(self) -> None:
        with TestClient(self.app) as client:
            project_id = self.prepare(client)
            timeline = client.get(f"/api/projects/{project_id}/timeline").json()
            first_hash = timeline["commits"][0]["hash"]

            client.post(
                f"/api/projects/{project_id}/commits/{first_hash}/annotations",
                json={"kind": "note", "body": "这里的重试逻辑踩过坑"},
            )
            client.post(
                f"/api/projects/{project_id}/bugs",
                json={
                    "title": "打包后首次启动闪退",
                    "error_text": "ModuleNotFoundError: no module named templates",
                },
            )
            client.post(
                f"/api/projects/{project_id}/notes",
                json={
                    "note_date": "2026-09-05",
                    "summary": "今天在调打包",
                    "issues": "",
                    "plan": "",
                },
            )

            response = client.get(
                f"/api/projects/{project_id}/timeline-events"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            kinds = [item["kind"] for item in payload["events"]]
            self.assertEqual(kinds.count("commit"), 3)
            self.assertEqual(kinds.count("annotation"), 1)
            self.assertEqual(kinds.count("bug"), 1)
            self.assertEqual(kinds.count("note"), 1)
            self.assertEqual(kinds.count("gap"), 1)
            self.assertEqual(payload["total_count"], len(payload["events"]))
            self.assertEqual(payload["truncated_count"], 0)
            self.assertEqual(payload["orphan_annotation_count"], 0)

            moments = [item["at"] for item in payload["events"]]
            self.assertEqual(moments, sorted(moments))

            # 批注锚定在它评论的那次提交上，而不是写批注的时刻。
            annotation = next(
                item for item in payload["events"] if item["kind"] == "annotation"
            )
            anchored = next(
                item
                for item in payload["events"]
                if item["kind"] == "commit"
                and item["commit"]["hash"] == first_hash
            )
            self.assertEqual(annotation["at"], anchored["at"])
            self.assertEqual(annotation["annotation"]["commit_hash"], first_hash)
            self.assertIsNone(annotation["commit"])

            # 空档紧跟在停止提交的那一条后面，而不是散在别处。
            second_commit_index = [
                index
                for index, item in enumerate(payload["events"])
                if item["kind"] == "commit"
            ][1]
            self.assertEqual(
                payload["events"][second_commit_index + 1]["kind"], "gap"
            )
            gap = payload["events"][second_commit_index + 1]["gap"]
            self.assertGreaterEqual(gap["days"], 3)

    def test_events_limit_keeps_the_most_recent_and_reports_truncation(self) -> None:
        with TestClient(self.app) as client:
            project_id = self.prepare(client)
            full = client.get(
                f"/api/projects/{project_id}/timeline-events"
            ).json()

            limited = client.get(
                f"/api/projects/{project_id}/timeline-events",
                params={"limit": 2},
            ).json()

            self.assertEqual(len(limited["events"]), 2)
            self.assertEqual(limited["total_count"], full["total_count"])
            self.assertEqual(
                limited["truncated_count"], full["total_count"] - 2
            )
            self.assertEqual(
                [item["key"] for item in limited["events"]],
                [item["key"] for item in full["events"][-2:]],
            )

    def test_events_carry_translated_subjects(self) -> None:
        with TestClient(self.app) as client:
            project_id = self.prepare(client)
            timeline = client.get(f"/api/projects/{project_id}/timeline").json()
            first_hash = timeline["commits"][0]["hash"]

            db = DevLogDB(self.db_path)
            try:
                db.save_commit_translations(project_id, {first_hash: "新增登录页面"})
            finally:
                db.close()

            payload = client.get(
                f"/api/projects/{project_id}/timeline-events"
            ).json()
            translated = next(
                item["commit"]["translated_subject"]
                for item in payload["events"]
                if item["kind"] == "commit" and item["commit"]["hash"] == first_hash
            )
            self.assertEqual(translated, "新增登录页面")

    def test_events_for_unknown_project_returns_404(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/api/projects/999/timeline-events")
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
