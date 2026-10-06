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
from typing import Any, Mapping

from devlog.core.llm.base import LLMClientBase, LLMError


DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT_SECONDS = 60
NETWORK_RETRY_ATTEMPTS = 3


# 配置文件里我们认识、并且允许网页端写入的字段。
CONFIG_KEYS = ("api_key", "model", "base_url")
# 指向自定义配置文件的环境变量：测试和高级用户用它避开 ~/.devlog。
CONFIG_PATH_ENV = "DEVLOG_CONFIG_PATH"


def default_config_path() -> Path:
    """本地配置文件位置；默认 ~/.devlog/config.toml。

    密钥只落在用户主目录下，永远不进任何 Git 仓库。测试用
    DEVLOG_CONFIG_PATH 指到临时文件，避免碰到用户真实的配置。
    """

    override = os.environ.get(CONFIG_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".devlog" / "config.toml"


def load_local_config(config_path: str | Path | None = None) -> dict[str, str]:
    """读取简单的 key = value 配置文件（TOML 子集）。

    默认位置是 ~/.devlog/config.toml。密钥按设计保存在所有 Git 仓库之外。
    """

    path = Path(config_path) if config_path is not None else default_config_path()
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
    """返回供 Web 界面使用的 LLM 配置。

    刻意不含明文密钥：只给掩码和"密钥来自哪里"。界面因此能显示状态，
    但就算页面被人看到也偷不走 key。
    """

    path = Path(config_path) if config_path is not None else default_config_path()
    config = load_local_config(path)
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    file_key = config.get("api_key")
    api_key = env_key or file_key
    if env_key:
        key_source = "env"
    elif file_key:
        key_source = "file"
    else:
        key_source = "none"
    return {
        "configured": "true" if api_key else "false",
        "model": config.get("model") or DEFAULT_MODEL,
        "base_url": config.get("base_url") or DEFAULT_BASE_URL,
        "api_key_hint": mask_api_key(api_key) if api_key else "",
        "key_source": key_source,
        "config_path": str(path),
    }


def mask_api_key(api_key: str) -> str:
    """把密钥打成 ``sk-1****abcd`` 这种掩码：够辨认，不够盗用。"""

    key = api_key.strip()
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def resolve_api_key(config_path: str | Path | None = None) -> str:
    """按 环境变量 > 配置文件 的顺序取出生效的密钥；都没有则返回空串。"""

    config = load_local_config(
        config_path if config_path is not None else default_config_path()
    )
    return os.environ.get("DEEPSEEK_API_KEY") or config.get("api_key") or ""


def _escape_config_value(value: str) -> str:
    """转义写进双引号的值，避免换行或引号把配置文件写坏。"""

    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


def save_local_config(
    updates: Mapping[str, str | None],
    config_path: str | Path | None = None,
) -> Path:
    """把改动合并写回 config.toml；值为 None 表示删掉这个键。

    只覆盖我们认识的字段，用户手写的其它配置原样保留，避免被网页
    上的一次保存顺手抹掉。
    """

    path = Path(config_path) if config_path is not None else default_config_path()
    config = load_local_config(path)
    for key, value in updates.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value

    lines = ["# DevLog 本地配置（自动生成，可手改；请勿提交到任何 Git 仓库）"]
    for key in CONFIG_KEYS:
        if key in config:
            lines.append(f'{key} = "{_escape_config_value(config.pop(key))}"')
    for key in sorted(config):
        lines.append(f'{key} = "{_escape_config_value(config[key])}"')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 类 Unix 系统上收紧权限：密钥文件不该让同机器其他用户读到。
    if os.name != "nt":
        path.chmod(0o600)
    return path


def probe_llm_connection(
    api_key: str,
    base_url: str,
    timeout: int = 10,
) -> tuple[bool, str]:
    """拉一次 ``/models`` 验证 key 和地址；这一步不产生生成费用。

    返回 (是否连通, 给用户看的中文说明)。这里刻意不做重试：用户要的是
    "现在到底通不通"，网络抖动让他再点一次即可。
    """

    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + api_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, f"API Key 无效或没有权限（HTTP {exc.code}）"
        return False, f"接口返回 HTTP {exc.code}，请检查接口地址"
    except (urllib.error.URLError, OSError) as exc:
        return False, f"连不上接口：{exc}"
    except (json.JSONDecodeError, ValueError) as exc:
        return False, f"接口返回的不是 JSON：{exc}"

    models: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        models = [
            item.get("id")
            for item in payload["data"]
            if isinstance(item, dict) and item.get("id")
        ]
    if models:
        return True, f"连接正常，接口返回 {len(models)} 个可用模型"
    return True, "连接正常"


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
        config = load_local_config(
            config_path if config_path is not None else default_config_path()
        )
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
