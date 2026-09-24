"""模块 6 测试：针对真实临时仓库的 CLI 编排测试。"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from devlog.cli import runner
from devlog.cli.main import main as cli_main
from devlog.core.review.models import (
    SECTION_ASSETS,
    SECTION_OVERVIEW,
    SECTION_TIMELINE,
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
)
from devlog.core.storage.database import DevLogDB


TZ = timezone(timedelta(hours=8))


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 9, 0, tzinfo=TZ)


def force_remove(path: Path) -> None:
    """即使 git 把对象文件标成只读，也要能删除临时仓库。"""

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


class CLIFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root)
        self.db_path = Path(self.root) / "devlog.db"
        commit(self.repo, "login.py", "def login(): ...\n", "feat: add login page", at(1))
        commit(self.repo, "login.py", "def login(): return True\n", "fix: login button", at(2))

    def tearDown(self) -> None:
        force_remove(self.root)

    def test_main_full_offline_flow(self) -> None:
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            code = cli_main(
                ["--db", str(self.db_path), "init", str(self.repo)]
            )
            self.assertEqual(code, 0)

            code = cli_main(
                ["--db", str(self.db_path), "scan", str(self.repo)]
            )
            self.assertEqual(code, 0)

            code = cli_main(
                [
                    "--db",
                    str(self.db_path),
                    "review",
                    "generate",
                    str(self.repo),
                    "--offline",
                ]
            )
        self.assertEqual(code, 0)

        with DevLogDB(self.db_path) as db:
            summaries = runner.cmd_review_list(db, self.repo)
            self.assertEqual(len(summaries), 1)
            draft_id = summaries[0].draft_id

            record = runner.cmd_review_show(db, draft_id)
            self.assertGreater(len(record.draft.claims), 0)
            self.assertTrue(
                    all(
                        item.claim.status == ClaimStatus.FACT
                        for item in record.stored_claims
                    )
                )

            target = runner.cmd_review_export(db, draft_id)

        self.assertTrue(target.exists())
        text = target.read_text(encoding="utf-8")
        self.assertIn("# 复盘：repo", text)
        self.assertIn("## 项目概述", text)
        self.assertEqual(target.parent.name, "retrospectives")
        self.assertEqual(target.parent.parent.name, "docs")

    def test_scan_is_idempotent_and_reset_rebuilds(self) -> None:
        with DevLogDB(self.db_path) as db:
            first = runner.cmd_scan(db, self.repo)
            second = runner.cmd_scan(db, self.repo)
            reset = runner.cmd_scan(db, self.repo, reset=True)

        self.assertEqual(first.inserted_events, 2)
        self.assertEqual(second.inserted_events, 0)
        self.assertTrue(reset.reset)
        self.assertEqual(reset.inserted_events, 2)
        self.assertEqual(reset.total_events, 2)

    def test_generate_requires_cached_events(self) -> None:
        with DevLogDB(self.db_path) as db:
            runner.cmd_init(db, self.repo)
            with self.assertRaises(runner.CLIUsageError):
                runner.cmd_review_generate(db, self.repo, offline=True)

    def test_online_generate_uses_provider_summaries(self) -> None:
        with DevLogDB(self.db_path) as db:
            runner.cmd_init(db, self.repo)
            runner.cmd_scan(db, self.repo)

            fake_client = mock.MagicMock()
            fake_summary = mock.MagicMock()
            fake_summary.title = "登录功能"
            fake_summary.kind = "feature"
            fake_summary.summary = "围绕登录页完成实现，并修复按钮问题。"
            fake_summary.sources = ()

            fake_asset = mock.MagicMock()
            fake_asset.name = "登录态校验函数"
            fake_asset.rationale = "登录与权限校验在不同页面反复出现。"
            fake_asset.sources = ()

            with mock.patch(
                "devlog.cli.runner.DeepSeekClient", return_value=fake_client
            ), mock.patch(
                "devlog.cli.runner.summarize_theme",
                return_value=fake_summary,
            ), mock.patch(
                "devlog.cli.runner.summarize_assets",
                return_value=[fake_asset],
            ):
                result = runner.cmd_review_generate(
                    db, self.repo, offline=False
                )

            self.assertFalse(result.offline)
            self.assertGreater(result.claim_count, 0)
            self.assertGreater(result.ai_pending_count, 0)

            record = runner.cmd_review_show(db, result.draft_id)
            timeline_claims = [
                item.claim
                for item in record.stored_claims
                if item.claim.section == SECTION_TIMELINE
            ]
            self.assertTrue(
                all(
                    "登录功能" in claim.text
                    for claim in timeline_claims
                )
            )

            asset_claims = [
                item.claim
                for item in record.stored_claims
                if item.claim.section == SECTION_ASSETS
            ]
            self.assertEqual(len(asset_claims), 1)
            self.assertIn("登录态校验函数", asset_claims[0].text)
            self.assertEqual(asset_claims[0].status, ClaimStatus.AI_PENDING)

    def test_init_rejects_non_git_directory(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            code = cli_main(["--db", str(self.db_path), "init", str(plain)])
        self.assertEqual(code, 1)


class CLIReviewConfirmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.db_path = Path(self.root) / "devlog.db"

    def tearDown(self) -> None:
        force_remove(self.root)

    def test_confirm_only_changes_ai_pending_claims(self) -> None:
        with DevLogDB(self.db_path) as db:
            project_id = db.register_project("demo", "D:/work/demo")
            draft = ReviewDraft(
                project_name="demo",
                range_start=at(1),
                range_end=at(2),
                claims=[
                    ReviewClaim(
                        section=SECTION_OVERVIEW,
                        text="共 1 次有效提交。",
                        status=ClaimStatus.FACT,
                    ),
                    ReviewClaim(
                        section=SECTION_OVERVIEW,
                        text="主题摘要（AI 推断）。",
                        status=ClaimStatus.AI_PENDING,
                    ),
                ],
                questions=[],
            )
            draft_id = db.save_review_draft(project_id, draft)
            record = db.load_review_draft(draft_id)
            fact_id = next(
                item.id
                for item in record.stored_claims
                if item.claim.status == ClaimStatus.FACT
            )
            pending_id = next(
                item.id
                for item in record.stored_claims
                if item.claim.status == ClaimStatus.AI_PENDING
            )

            first = runner.cmd_review_confirm(db, draft_id, claim_ids=[fact_id])
            self.assertEqual(first.changed, 0)
            self.assertEqual(first.remaining_pending, 1)

            second = runner.cmd_review_confirm(
                db, draft_id, claim_ids=[pending_id], note="人工复核通过"
            )
            self.assertEqual(second.changed, 1)
            self.assertEqual(second.remaining_pending, 0)

            reloaded = db.load_review_draft(draft_id)
            statuses = {item.id: item.claim for item in reloaded.stored_claims}
            self.assertEqual(statuses[fact_id].status, ClaimStatus.FACT)
            self.assertEqual(statuses[pending_id].status, ClaimStatus.CONFIRMED)
            self.assertEqual(statuses[pending_id].user_note, "人工复核通过")

    def test_confirm_all_option(self) -> None:
        with DevLogDB(self.db_path) as db:
            project_id = db.register_project("demo", "D:/work/demo")
            draft = ReviewDraft(
                project_name="demo",
                range_start=at(1),
                range_end=at(2),
                claims=[
                    ReviewClaim(
                        section=SECTION_OVERVIEW,
                        text="AI 推断一",
                        status=ClaimStatus.AI_PENDING,
                    ),
                    ReviewClaim(
                        section=SECTION_OVERVIEW,
                        text="AI 推断二",
                        status=ClaimStatus.AI_PENDING,
                    ),
                ],
            )
            draft_id = db.save_review_draft(project_id, draft)

            result = runner.cmd_review_confirm(db, draft_id, confirm_all=True)
            self.assertEqual(result.changed, 2)
            self.assertEqual(result.remaining_pending, 0)

    def test_confirm_requires_ids_or_all(self) -> None:
        with DevLogDB(self.db_path) as db:
            project_id = db.register_project("demo", "D:/work/demo")
            draft_id = db.save_review_draft(
                project_id,
                ReviewDraft(
                    project_name="demo",
                    range_start=at(1),
                    range_end=at(2),
                    claims=[],
                ),
            )
            with self.assertRaises(runner.CLIUsageError):
                runner.cmd_review_confirm(db, draft_id)


class CommitTranslationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.repo = make_repo(self.root)
        self.db_path = Path(self.root) / "devlog.db"
        commit(
            self.repo,
            "login.py",
            "def login(): ...\n",
            "feat: add login page",
            at(1),
        )
        commit(
            self.repo,
            "login.py",
            "def login(): return True\n",
            "fix: login button",
            at(2),
        )

    def tearDown(self) -> None:
        force_remove(self.root)

    def test_translate_caches_new_subjects_and_is_idempotent(self) -> None:
        with DevLogDB(self.db_path) as db:
            project_id = runner.cmd_init(db, self.repo).project_id
            runner.cmd_scan(db, self.repo)
            events = db.list_events(project_id, include_noise=True)

            fake = mock.MagicMock()
            fake.complete_json.return_value = {
                event.hash: "中文提交说明" for event in events
            }
            with mock.patch(
                "devlog.cli.runner.DeepSeekClient", return_value=fake
            ):
                first = runner.cmd_translate_commits(db, project_id)
                second = runner.cmd_translate_commits(db, project_id)

            self.assertEqual(first.translated_count, 2)
            self.assertEqual(first.remaining_count, 0)
            self.assertEqual(second.translated_count, 0)
            self.assertEqual(second.remaining_count, 0)
            self.assertEqual(fake.complete_json.call_count, 1)

            cached = db.list_commit_translations(project_id)
            self.assertEqual(len(cached), 2)
            self.assertTrue(
                all(value == "中文提交说明" for value in cached.values())
            )


if __name__ == "__main__":
    unittest.main()
