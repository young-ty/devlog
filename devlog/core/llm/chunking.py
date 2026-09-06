"""Deterministic text chunking and chunked summarization.

Long histories are split into budget-sized chunks, summarized per chunk,
then merged into one final summary. This keeps every request inside the
model context window and keeps token cost predictable.
"""

from __future__ import annotations

from devlog.core.llm.base import LLMClientBase


SUMMARY_INSTRUCTION = (
    "Summarize the following development log in Chinese, 3-5 sentences. "
    "Only state what the log supports. Do not invent reasons or plans."
)

MERGE_INSTRUCTION = (
    "These are chunk summaries of one development log. Merge them into one "
    "coherent Chinese summary, removing repetition. Do not add facts."
)


def chunk_texts(texts: list[str], max_chars_per_chunk: int) -> list[list[str]]:
    """Split lines into chunks that each fit the character budget."""

    if max_chars_per_chunk <= 0:
        raise ValueError("max_chars_per_chunk must be positive")

    chunks: list[list[str]] = []
    current: list[str] = []
    current_size = 0

    for text in texts:
        cost = len(text) + 1  # account for the newline
        if current and current_size + cost > max_chars_per_chunk:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(text)
        current_size += cost

    if current:
        chunks.append(current)
    return chunks


def summarize_texts_in_chunks(
    texts: list[str],
    client: LLMClientBase,
    max_chars_per_chunk: int = 4000,
    merge: bool = True,
) -> str:
    """Summarize texts chunk by chunk and optionally merge the results."""

    if not texts:
        return ""

    chunks = chunk_texts(texts, max_chars_per_chunk)
    summaries: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        lines = "\n".join("- " + line for line in chunk)
        prompt = SUMMARY_INSTRUCTION + f"\n\nChunk {index}/{len(chunks)}:\n{lines}"
        summary = client.complete(prompt).strip()
        summaries.append(summary)

    if merge and len(summaries) > 1:
        numbered = "\n".join(
            f"{index}. {summary}" for index, summary in enumerate(summaries, start=1)
        )
        merge_prompt = MERGE_INSTRUCTION + "\n\n" + numbered
        return client.complete(merge_prompt).strip()

    return summaries[0]
