"""LLM 供应商抽象与分块摘要。"""

from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.chunking import chunk_texts, summarize_texts_in_chunks
from devlog.core.llm.deepseek import (
    DeepSeekClient,
    default_config_path,
    llm_settings,
    load_local_config,
    mask_api_key,
    probe_llm_connection,
    resolve_api_key,
    save_local_config,
)
from devlog.core.llm.themes import ThemeSummary, rule_based_summary, summarize_theme
from devlog.core.llm.translation import translate_commit_subjects

__all__ = [
    "DeepSeekClient",
    "LLMClientBase",
    "LLMError",
    "ThemeSummary",
    "chunk_texts",
    "default_config_path",
    "llm_settings",
    "load_local_config",
    "mask_api_key",
    "probe_llm_connection",
    "resolve_api_key",
    "rule_based_summary",
    "save_local_config",
    "summarize_texts_in_chunks",
    "summarize_theme",
    "translate_commit_subjects",
]
