"""把 Git commit subject 批量翻译成简体中文。

原始 commit subject 始终是事实来源。翻译只是 AI 生成的显示层，
缓存在本地，永远不会写回 Git。
"""

from __future__ import annotations

from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.llm.themes import complete_json_with_retry


BATCH_SIZE = 20

_PROMPT_TEMPLATE = """Translate each Git commit subject into concise,
natural Simplified Chinese. Keep proper nouns and technical terms in their
usual Chinese or English form; do not add explanation. Return ONLY a JSON
object whose keys are the exact full hashes and whose values are the Chinese
translations.

Commit subjects:
{lines}
"""


def translate_commit_subjects(
    client: LLMClientBase,
    items: list[tuple[str, str]],
    batch_size: int = BATCH_SIZE,
) -> dict[str, str]:
    """按批翻译 commit subject；返回 hash -> 中文文本 的映射。"""

    translations: dict[str, str] = {}
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        lines = [
            f"{commit_hash}: {subject}" for commit_hash, subject in batch
        ]
        prompt = _PROMPT_TEMPLATE.format(lines="\n".join(lines))
        try:
            data = complete_json_with_retry(client, prompt)
        except LLMError:
            # 单个批次失败不应拖垮整个项目；调用方下次可重试剩余 hash。
            continue

        if not isinstance(data, dict):
            continue
        for commit_hash, subject in batch:
            value = data.get(commit_hash)
            if isinstance(value, str) and value.strip():
                translations[commit_hash] = value.strip()
    return translations
