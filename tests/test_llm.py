"""Module 4 tests: LLM abstraction, chunking and structured summaries.

No real network call is made: a FakeClient stands in for the provider so
tests stay fast, deterministic and free.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.chunking import chunk_texts, summarize_texts_in_chunks
from devlog.core.llm.deepseek import DeepSeekClient, load_local_config
from devlog.core.llm.themes import (
    ThemeSummary,
    complete_json_with_retry,
    summarize_theme,
)
from devlog.core.llm.translation import translate_commit_subjects
from devlog.core.theming.models import Theme


TZ = timezone(timedelta(hours=8))


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 9, 0, tzinfo=TZ)


class FakeClient(LLMClientBase):
    def __init__(self) -> None:
        self.complete_prompts: list[str] = []
        self.json_prompts: list[str] = []
        self.fail_json_times = 0

    def complete(self, prompt: str) -> str:
        self.complete_prompts.append(prompt)
        return "summary"

    def complete_json(self, prompt: str) -> dict:
        self.json_prompts.append(prompt)
        if self.fail_json_times > 0:
            self.fail_json_times -= 1
            raise LLMError("invalid JSON")
        return {
            "title": "login",
            "kind": "feature",
            "summary": "Implemented the login feature.",
            "sources": [f"{i:040d}" for i in (1, 2)],
        }


class FakeTranslationClient(LLMClientBase):
    def __init__(self) -> None:
        self.json_prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        return ""

    def complete_json(self, prompt: str) -> dict:
        self.json_prompts.append(prompt)
        return {
            f"{1:040d}": "新增登录页面",
            f"{2:040d}": "修复登录按钮",
        }


def make_event(number: int, day: int) -> CommitEvent:
    return CommitEvent(
        hash=f"{number:040d}",
        short_hash=f"{number:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=at(day),
        message_subject="feat: add login page",
        files_changed=1,
        insertions=1,
        deletions=0,
        parents_count=0,
        noise_type=NoiseType.NONE,
    )


class ChunkingTests(unittest.TestCase):
    def test_chunk_texts_respects_budget(self) -> None:
        texts = ["aaaaaa", "bbbbbb", "cccccc"]
        chunks = chunk_texts(texts, max_chars_per_chunk=20)
        self.assertEqual([len(chunk) for chunk in chunks], [2, 1])

    def test_chunk_texts_rejects_bad_budget(self) -> None:
        with self.assertRaises(ValueError):
            chunk_texts(["a"], max_chars_per_chunk=0)

    def test_summarize_empty_texts_skips_calls(self) -> None:
        client = FakeClient()
        self.assertEqual(summarize_texts_in_chunks([], client), "")
        self.assertEqual(client.complete_prompts, [])

    def test_summarize_single_chunk_does_not_merge(self) -> None:
        client = FakeClient()
        text = "commit line " + "x" * 100
        result = summarize_texts_in_chunks([text], client, max_chars_per_chunk=4000)
        self.assertEqual(result, "summary")
        self.assertEqual(len(client.complete_prompts), 1)
        self.assertIn("Chunk 1/1", client.complete_prompts[0])

    def test_summarize_many_chunks_merges(self) -> None:
        client = FakeClient()
        texts = ["line " + str(i) + "y" * 90 for i in range(10)]
        result = summarize_texts_in_chunks(texts, client, max_chars_per_chunk=200)

        self.assertEqual(result, "summary")
        calls = client.complete_prompts
        self.assertGreater(len(calls), 2)
        merge_prompt = calls[-1]
        self.assertIn("Merge them into one", merge_prompt)


class ThemeSummaryTests(unittest.TestCase):
    def _theme(self) -> Theme:
        return Theme(
            id="theme-1",
            title="login",
            kind="feature",
            commit_hashes=(f"{1:040d}", f"{2:040d}"),
            started_at=at(1),
            ended_at=at(2),
            commit_count=2,
        )

    def test_summarize_theme_valid(self) -> None:
        client = FakeClient()
        result = summarize_theme(self._theme(), [make_event(1, 1), make_event(2, 2)], client)
        self.assertEqual(result.title, "login")
        self.assertEqual(result.kind, "feature")
        self.assertEqual(len(result.sources), 2)

    def test_summarize_empty_theme_skips_calls(self) -> None:
        client = FakeClient()
        result = summarize_theme(self._theme(), [], client)
        self.assertEqual(result.summary, "")
        self.assertEqual(client.json_prompts, [])

    def test_retry_once_after_bad_json(self) -> None:
        client = FakeClient()
        client.fail_json_times = 1
        result = summarize_theme(self._theme(), [make_event(1, 1)], client)

        self.assertEqual(len(client.json_prompts), 2)
        self.assertIn("valid JSON only", client.json_prompts[1])
        self.assertEqual(result.title, "login")

    def test_always_bad_json_degrades_to_error(self) -> None:
        client = FakeClient()
        client.fail_json_times = 999
        with self.assertRaises(LLMError):
            complete_json_with_retry(client, "prompt", attempts=2)
        self.assertEqual(len(client.json_prompts), 2)

    def test_missing_field_rejected(self) -> None:
        with self.assertRaises(LLMError):
            ThemeSummary.from_dict({"title": "x"})


class ConfigTests(unittest.TestCase):
    def test_load_local_config_parses_key_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '# comment\napi_key = "sk-test"\nmodel = "deepseek-chat"\n',
                encoding="utf-8",
            )
            config = load_local_config(path)
        self.assertEqual(config["api_key"], "sk-test")
        self.assertEqual(config["model"], "deepseek-chat")

    def test_deepseek_client_reads_model_and_base_url_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'api_key = "sk-test"\n'
                'model = "deepseek-coder"\n'
                'base_url = "https://api.example.com/"\n',
                encoding="utf-8",
            )
            client = DeepSeekClient(config_path=path)
        self.assertEqual(client.model, "deepseek-coder")
        self.assertEqual(client.base_url, "https://api.example.com")


class TranslationTests(unittest.TestCase):
    def test_translate_commit_subjects_returns_chinese_map(self) -> None:
        client = FakeTranslationClient()
        items = [
            (f"{1:040d}", "feat: add login page"),
            (f"{2:040d}", "fix: login button"),
        ]

        result = translate_commit_subjects(client, items)

        self.assertEqual(result[f"{1:040d}"], "新增登录页面")
        self.assertEqual(result[f"{2:040d}"], "修复登录按钮")
        self.assertEqual(len(client.json_prompts), 1)
        self.assertIn(f"{1:040d}", client.json_prompts[0])

    def test_translate_commit_subjects_handles_empty_list(self) -> None:
        client = FakeTranslationClient()
        self.assertEqual(translate_commit_subjects(client, []), {})
        self.assertEqual(client.json_prompts, [])


if __name__ == "__main__":
    unittest.main()
