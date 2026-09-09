"""与具体供应商无关的 LLM 接口。

业务代码只依赖这个接口，不依赖任何具体厂商。DeepSeek 是默认供应商；
以后接入 OpenAI/Ollama 等只需新增一个类与一条配置。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    """当 LLM 调用或其输出不可用时抛出。"""


class LLMClientBase(ABC):
    """每个 LLM 供应商都必须实现 complete 与 complete_json。"""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """返回该 prompt 的纯文本补全结果。"""

    @abstractmethod
    def complete_json(self, prompt: str) -> dict[str, Any]:
        """返回解析后的 JSON 对象；输出非法时抛出 LLMError。"""

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"
