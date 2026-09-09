"""确定性的文本分块与分块摘要。

长历史会被切分为符合预算大小的多个分块，先逐块摘要，再合并成最终
摘要。这样每次请求都保持在模型上下文窗口内，token 成本也可预测。
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
    """把多段文本切成每个都符合字符预算的分块。"""

    if max_chars_per_chunk <= 0:
        raise ValueError("max_chars_per_chunk must be positive")

    chunks: list[list[str]] = []
    current: list[str] = []
    current_size = 0

    for text in texts:
        cost = len(text) + 1  # 把换行符算进长度
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
    """逐块摘要文本，并可选地把各块结果合并为最终摘要。"""

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
