"""基于 OpenAI 兼容聊天接口的 DeepSeek 供应商实现。

刻意只使用标准库：V1 的 HTTP 与配置解析不需要任何第三方依赖。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from devlog.core.llm.base import LLMClientBase, LLMError


DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 60
NETWORK_RETRY_ATTEMPTS = 3


def load_local_config(config_path: str | Path | None = None) -> dict[str, str]:
    """读取简单的 key = value 配置文件（TOML 子集）。

    默认位置是 ~/.devlog/config.toml。密钥按设计保存在所有 Git 仓库之外。
    """

    path = Path(config_path) if config_path is not None else Path.home() / ".devlog" / "config.toml"
    config: dict[str, str] = {}
    if not path.exists():
        return config

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def llm_settings(config_path: str | Path | None = None) -> dict[str, str]:
    """返回供 Web 界面使用的安全（不含密钥）LLM 配置。"""

    config = load_local_config(config_path)
    api_key = os.environ.get("DEEPSEEK_API_KEY") or config.get("api_key")
    return {
        "configured": "true" if api_key else "false",
        "model": config.get("model") or DEFAULT_MODEL,
        "base_url": config.get("base_url") or DEFAULT_BASE_URL,
    }


class DeepSeekClient(LLMClientBase):
    """调用 DeepSeek 的 OpenAI 兼容 chat completions API。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        config_path: str | Path | None = None,
    ) -> None:
        config = load_local_config(config_path)
        resolved_key = (
            api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or config.get("api_key")
        )
        if not resolved_key:
            raise LLMError(
                "missing DeepSeek API key: pass api_key, set DEEPSEEK_API_KEY "
                "or create ~/.devlog/config.toml"
            )
        self.api_key = resolved_key
        self.model = model or config.get("model") or DEFAULT_MODEL
        raw_base_url = base_url or config.get("base_url") or DEFAULT_BASE_URL
        self.base_url = raw_base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "stream": False,
        }
        data = self._post_json(payload)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected DeepSeek response shape") from exc

    def complete_json(self, prompt: str) -> dict[str, Any]:
        content = self.complete(prompt)
        try:
            return _parse_json_content(content)
        except ValueError as exc:
            raise LLMError("model output is not valid JSON") from exc

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")

        last_error: Exception | None = None
        for attempt in range(NETWORK_RETRY_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise LLMError("DeepSeek response is not a JSON object")
                return parsed
            except (urllib.error.URLError, OSError, json.JSONDecodeError, LLMError) as exc:
                last_error = exc
                if attempt < NETWORK_RETRY_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)

        raise LLMError(f"DeepSeek request failed after retries: {last_error}")


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("JSON value must be an object")
    return parsed
