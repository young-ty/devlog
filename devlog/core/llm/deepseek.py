"""DeepSeek provider using its OpenAI-compatible chat endpoint.

Uses only the standard library on purpose: no third-party dependency is
required for HTTP or configuration in V1.
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


DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 60
NETWORK_RETRY_ATTEMPTS = 3


def load_local_config(config_path: str | Path | None = None) -> dict[str, str]:
    """Read a simple key = value config file (TOML-like subset).

    The default location is ~/.devlog/config.toml. Secret values stay
    outside every git repository by design.
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


class DeepSeekClient(LLMClientBase):
    """Call DeepSeek's OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        config = load_local_config()
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
        self.model = model
        self.base_url = base_url.rstrip("/")
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
