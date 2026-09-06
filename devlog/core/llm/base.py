"""Provider-agnostic LLM interface.

Business code depends on this interface, never on a concrete vendor.
DeepSeek is the default provider; adding OpenAI/Ollama/etc means adding
one new class and a configuration entry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    """Raised when an LLM call or its output cannot be used."""


class LLMClientBase(ABC):
    """Every LLM provider must implement complete and complete_json."""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Return plain text completion for the prompt."""

    @abstractmethod
    def complete_json(self, prompt: str) -> dict[str, Any]:
        """Return a parsed JSON object; raise LLMError on invalid output."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"
