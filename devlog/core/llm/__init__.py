"""LLM provider abstraction and chunked summarization."""

from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.chunking import chunk_texts, summarize_texts_in_chunks
from devlog.core.llm.deepseek import (
    DeepSeekClient,
    llm_settings,
    load_local_config,
)
from devlog.core.llm.themes import ThemeSummary, rule_based_summary, summarize_theme
from devlog.core.llm.translation import translate_commit_subjects

__all__ = [
    "DeepSeekClient",
    "LLMClientBase",
    "LLMError",
    "ThemeSummary",
    "chunk_texts",
    "llm_settings",
    "load_local_config",
    "rule_based_summary",
    "summarize_texts_in_chunks",
    "summarize_theme",
    "translate_commit_subjects",
]
