"""Batch translation of Git commit subjects into Simplified Chinese.

The original commit subject remains the source of truth. Translations are
an AI-derived display layer cached locally and never written back to Git.
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
    """Translate commit subjects in batches; returns hash -> Chinese text."""

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
            # A failed batch should not fail the whole project; the caller
            # can retry the remaining hashes next time.
            continue

        if not isinstance(data, dict):
            continue
        for commit_hash, subject in batch:
            value = data.get(commit_hash)
            if isinstance(value, str) and value.strip():
                translations[commit_hash] = value.strip()
    return translations
