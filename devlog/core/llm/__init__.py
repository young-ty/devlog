"""LLM provider abstraction and chunked summarization."""

from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.chunking import chunk_texts, summarize_texts_in_chunks
from devlog.core.llm.deepseek import DeepSeekClient, load_local_config
from devlog.core.llm.themes import ThemeSummary, summarize_theme

__all__ = [
    "DeepSeekClient",
    "LLMClientBase",
    "LLMError",
    "ThemeSummary",
    "chunk_texts",
    "load_local_config",
    "summarize_texts_in_chunks",
    "summarize_theme",
]
