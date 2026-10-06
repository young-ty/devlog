"""模块 4 测试：LLM 抽象、分块与结构化摘要。

不会发起真实网络调用：FakeClient 充当供应商，让测试保持快速、
确定且零成本。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.chunking import chunk_texts, summarize_texts_in_chunks
from devlog.core.llm.deepseek import (
    CONFIG_PATH_ENV,
    DEFAULT_MODEL,
    DeepSeekClient,
    default_config_path,
    llm_settings,
    load_local_config,
    mask_api_key,
    probe_llm_connection,
    resolve_api_key,
    save_local_config,
)
from devlog.core.llm.themes import (
    AssetSummary,
    ThemeSummary,
    complete_json_with_retry,
    summarize_assets,
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


class FakeAssetClient(LLMClientBase):
    """只回答"可复用资产"那一次调用。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.json_prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        return "unused"

    def complete_json(self, prompt: str) -> dict:
        self.json_prompts.append(prompt)
        return self.payload


class AssetSummaryTests(unittest.TestCase):
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

    def _summary(self) -> ThemeSummary:
        return ThemeSummary(
            title="登录功能",
            kind="feature",
            summary="实现了登录页与接口。",
            sources=(f"{1:040d}",),
        )

    def test_assets_are_parsed_and_bounded(self) -> None:
        payload = {
            "assets": [
                {
                    "name": f"资产{i}",
                    "rationale": "可以复用。",
                    "sources": [f"{1:040d}"],
                }
                for i in range(8)
            ]
        }
        client = FakeAssetClient(payload)
        assets = summarize_assets([self._theme()], [self._summary()], client)

        self.assertEqual(len(assets), 5)
        self.assertEqual(assets[0].name, "资产0")
        self.assertEqual(assets[0].sources, (f"{1:040d}",))
        self.assertIn("reusable assets", client.json_prompts[0])

    def test_empty_asset_list_is_allowed(self) -> None:
        client = FakeAssetClient({"assets": []})
        self.assertEqual(
            summarize_assets([self._theme()], [self._summary()], client),
            [],
        )

    def test_prompt_demands_a_quality_bar_instead_of_padding(self) -> None:
        """提示词只说"最多 5 条"，模型就会当配额凑满，所以必须写死质量门槛。"""

        client = FakeAssetClient({"assets": []})
        summarize_assets([self._theme()], [self._summary()], client)
        prompt = client.json_prompts[0]

        self.assertIn("One-off chores", prompt)
        self.assertIn("Returning fewer is better than padding", prompt)
        self.assertIn("empty list", prompt)
        self.assertIn("archiving demo images", prompt)

    def test_no_themes_skips_the_call(self) -> None:
        client = FakeAssetClient({"assets": []})
        self.assertEqual(summarize_assets([], [], client), [])
        self.assertEqual(client.json_prompts, [])

    def test_missing_key_is_rejected(self) -> None:
        client = FakeAssetClient({"foo": []})
        with self.assertRaises(LLMError):
            summarize_assets([self._theme()], [self._summary()], client)

    def test_mismatched_summaries_raise(self) -> None:
        client = FakeAssetClient({"assets": []})
        with self.assertRaises(ValueError):
            summarize_assets([self._theme()], [], client)

    def test_asset_without_name_is_rejected(self) -> None:
        with self.assertRaises(LLMError):
            AssetSummary.from_dict({"rationale": "缺名字", "sources": []})


class ConfigTests(unittest.TestCase):
    def test_default_model_is_deepseek_v4_flash(self) -> None:
        self.assertEqual(DEFAULT_MODEL, "deepseek-v4-flash")

    def test_load_local_config_parses_key_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '# comment\napi_key = "sk-test"\nmodel = "deepseek-v4-flash"\n',
                encoding="utf-8",
            )
            config = load_local_config(path)
        self.assertEqual(config["api_key"], "sk-test")
        self.assertEqual(config["model"], "deepseek-v4-flash")

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


class LocalConfigWriteTests(unittest.TestCase):
    """配置文件写入：网页上填的密钥要能存、能改、能删。

    全部走临时目录：碰到用户真实的 ~/.devlog/config.toml 就是把测试库
    和真实密钥搅在一起，属于测试事故。
    """

    def test_default_config_path_follows_env_override(self) -> None:
        with patch.dict(os.environ, {CONFIG_PATH_ENV: str(Path("tmp") / "c.toml")}):
            self.assertEqual(default_config_path(), Path("tmp") / "c.toml")

    def test_default_config_path_falls_back_to_home(self) -> None:
        with patch.dict(os.environ, {CONFIG_PATH_ENV: ""}):
            self.assertEqual(
                default_config_path(),
                Path.home() / ".devlog" / "config.toml",
            )

    def test_save_writes_new_file_and_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.toml"
            save_local_config({"api_key": "sk-abcdef123456"}, path)
            self.assertTrue(path.exists())
            config = load_local_config(path)
        self.assertEqual(config["api_key"], "sk-abcdef123456")

    def test_save_merges_instead_of_replacing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_local_config({"api_key": "sk-abcdef123456"}, path)
            # 第二次只改模型：密钥必须原样留着，否则用户改个模型就把 key 弄丢了
            save_local_config({"model": "deepseek-chat"}, path)
            config = load_local_config(path)
        self.assertEqual(config["api_key"], "sk-abcdef123456")
        self.assertEqual(config["model"], "deepseek-chat")

    def test_save_with_none_removes_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_local_config(
                {"api_key": "sk-abcdef123456", "model": "deepseek-chat"},
                path,
            )
            save_local_config({"api_key": None}, path)
            config = load_local_config(path)
        self.assertNotIn("api_key", config)
        self.assertEqual(config["model"], "deepseek-chat")

    def test_save_keeps_keys_we_do_not_know_about(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'api_key = "sk-old"\ncustom_flag = "keep-me"\n',
                encoding="utf-8",
            )
            save_local_config({"model": "deepseek-chat"}, path)
            config = load_local_config(path)
        self.assertEqual(config["custom_flag"], "keep-me")
        self.assertEqual(config["api_key"], "sk-old")

    def test_save_keeps_odd_values_on_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_local_config(
                {"api_key": 'sk-weird"\nvalue', "model": "deepseek-chat"},
                path,
            )
            text = path.read_text(encoding="utf-8")
            config = load_local_config(path)
        # 文件结构应该是"注释 + api_key + model"三行：值里的换行必须
        # 压平，多一行就多一条假配置
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("#"))
        self.assertTrue(config["api_key"].startswith("sk-weird"))
        self.assertEqual(config["model"], "deepseek-chat")


class ApiKeyMaskTests(unittest.TestCase):
    def test_masks_the_middle_of_a_key(self) -> None:
        self.assertEqual(mask_api_key("sk-1234567890abcd"), "sk-1****abcd")

    def test_short_values_are_fully_hidden(self) -> None:
        self.assertEqual(mask_api_key("sk-1"), "****")
        self.assertEqual(mask_api_key("   "), "****")

    def test_surrounding_whitespace_is_ignored(self) -> None:
        self.assertEqual(mask_api_key("  sk-1234567890abcd  "), "sk-1****abcd")


class ResolveApiKeyTests(unittest.TestCase):
    def test_environment_wins_over_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_local_config({"api_key": "sk-from-file"}, path)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-from-env"}):
                self.assertEqual(resolve_api_key(path), "sk-from-env")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                self.assertEqual(resolve_api_key(path), "sk-from-file")

    def test_missing_everywhere_gives_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                self.assertEqual(resolve_api_key(path), "")

    def test_llm_settings_reports_hint_and_source_without_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            save_local_config(
                {"api_key": "sk-1234567890abcd", "model": "deepseek-chat"},
                path,
            )
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                settings = llm_settings(path)
        self.assertEqual(settings["configured"], "true")
        self.assertEqual(settings["key_source"], "file")
        self.assertEqual(settings["api_key_hint"], "sk-1****abcd")
        self.assertEqual(settings["model"], "deepseek-chat")
        self.assertNotIn("sk-1234567890abcd", json.dumps(settings))

    def test_llm_settings_says_none_when_nothing_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                settings = llm_settings(path)
        self.assertEqual(settings["configured"], "false")
        self.assertEqual(settings["key_source"], "none")
        self.assertEqual(settings["api_key_hint"], "")
        self.assertEqual(settings["model"], DEFAULT_MODEL)


class _FakeResponse:
    """够用的假响应：probe 只用到上下文管理器和 read()。"""

    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class ProbeConnectionTests(unittest.TestCase):
    """探活要区分"通"、"key 不对"和"压根连不上"。"""

    URLOPEN = "devlog.core.llm.deepseek.urllib.request.urlopen"

    def test_reports_success_and_how_many_models_came_back(self) -> None:
        body = json.dumps(
            {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}
        )
        with patch(self.URLOPEN, return_value=_FakeResponse(body)):
            ok, message = probe_llm_connection("sk-test", "https://api.deepseek.com")
        self.assertTrue(ok)
        self.assertIn("2", message)

    def test_strips_the_trailing_slash_before_building_the_url(self) -> None:
        with patch(
            self.URLOPEN,
            return_value=_FakeResponse('{"data": []}'),
        ) as opened:
            probe_llm_connection("sk-test", "https://api.example.com/")
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.example.com/models")

    def test_rejects_an_invalid_key(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.deepseek.com/models", 401, "Unauthorized", {}, None
        )
        with patch(self.URLOPEN, side_effect=error):
            ok, message = probe_llm_connection("sk-bad", "https://api.deepseek.com")
        self.assertFalse(ok)
        self.assertIn("401", message)

    def test_reports_a_network_failure(self) -> None:
        with patch(self.URLOPEN, side_effect=urllib.error.URLError("boom")):
            ok, message = probe_llm_connection("sk-test", "https://api.deepseek.com")
        self.assertFalse(ok)
        self.assertIn("连不上", message)


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
