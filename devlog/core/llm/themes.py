"""通过 LLM 客户端生成的结构化主题摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from devlog.core.git_source.models import CommitEvent
from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.theming.models import Theme


KIND_LABELS_ZH = {
    "feature": "功能开发",
    "bugfix": "问题修复",
    "refactor": "重构",
    "docs": "文档",
    "test": "测试",
    "perf": "性能优化",
    "build": "构建",
    "other": "其他",
}


THEME_JSON_INSTRUCTION = (
    "Return a JSON object only, with exactly these keys: "
    '"title" (short Chinese title), "kind" (feature/bugfix/refactor/docs/'
    'test/perf/build/other), "summary" (Chinese, 3-5 sentences, grounded '
    'in the commits), and "sources" (list of commit hashes you relied on).'
)

ASSET_JSON_INSTRUCTION = (
    "Now look at the themes as a whole and find work that is worth "
    'extracting into reusable assets. Return a JSON object only, with '
    'exactly one key: "assets". Its value is a list of objects, each with '
    '"name" (short Chinese name of the reusable function/module/approach), '
    '"rationale" (Chinese, why it is worth extracting and where it would be '
    'reused), and "sources" (list of commit hashes you relied on). '
    "Return at most 5 items, ordered by value. If nothing is worth "
    "extracting, return an empty list. Do not invent work that the "
    "themes do not mention."
)


@dataclass(frozen=True)
class ThemeSummary:
    """某个主题经过校验的结构化输出。"""

    title: str
    kind: str
    summary: str
    sources: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThemeSummary":
        title = data.get("title")
        kind = data.get("kind")
        summary = data.get("summary")
        sources = data.get("sources")

        if not isinstance(title, str) or not title.strip():
            raise LLMError("ThemeSummary requires a non-empty string title")
        if not isinstance(kind, str) or not kind.strip():
            raise LLMError("ThemeSummary requires a non-empty string kind")
        if not isinstance(summary, str) or not summary.strip():
            raise LLMError("ThemeSummary requires a non-empty string summary")
        if not isinstance(sources, list) or not all(
            isinstance(item, str) for item in sources
        ):
            raise LLMError("ThemeSummary requires a sources list of hashes")

        return cls(
            title=title,
            kind=kind,
            summary=summary,
            sources=tuple(sources),
        )


@dataclass(frozen=True)
class AssetSummary:
    """一个"值得沉淀为可复用资产"的候选。"""

    name: str
    rationale: str
    sources: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetSummary":
        name = data.get("name")
        rationale = data.get("rationale")
        sources = data.get("sources")

        if not isinstance(name, str) or not name.strip():
            raise LLMError("AssetSummary requires a non-empty string name")
        if not isinstance(rationale, str) or not rationale.strip():
            raise LLMError("AssetSummary requires a non-empty string rationale")
        if not isinstance(sources, list) or not all(
            isinstance(item, str) for item in sources
        ):
            raise LLMError("AssetSummary requires a sources list of hashes")

        return cls(name=name, rationale=rationale, sources=tuple(sources))


def complete_json_with_retry(
    client: LLMClientBase,
    prompt: str,
    attempts: int = 2,
) -> dict[str, Any]:
    """请求 JSON；失败时带提示重试一次，仍失败则抛出错误。"""

    last_error: LLMError | None = None
    for attempt in range(max(1, attempts)):
        try:
            return client.complete_json(prompt)
        except LLMError as exc:
            last_error = exc
            if attempt < attempts - 1:
                prompt = (
                    prompt
                    + "\n\nNote: your previous output was not valid JSON. "
                    + "Return valid JSON only."
                )
    raise LLMError(
        f"invalid JSON after {max(1, attempts)} attempt(s): {last_error}"
    )


def summarize_theme(
    theme: Theme,
    commits: list[CommitEvent],
    client: LLMClientBase,
) -> ThemeSummary:
    """为一个主题生成经过校验的结构化摘要。"""

    if not commits:
        return ThemeSummary(
            title=theme.title,
            kind=theme.kind,
            summary="",
            sources=(),
        )

    lines = _commit_lines(commits)
    prompt = (
        f"Theme metadata: id={theme.id}, title={theme.title}, kind={theme.kind}\n"
        f"Commits in this theme:\n"
        + "\n".join("- " + line for line in lines)
        + "\n\n"
        + THEME_JSON_INSTRUCTION
    )
    data = complete_json_with_retry(client, prompt)
    return ThemeSummary.from_dict(data)


def summarize_assets(
    themes: list[Theme],
    theme_summaries: list[ThemeSummary],
    client: LLMClientBase,
    max_assets: int = 5,
) -> list[AssetSummary]:
    """横跨所有主题，归纳出值得沉淀为可复用资产的候选。

    这是"AI 该回答的问题"，不是"该反问用户的问题"：用户没法凭空回忆
    自己写过哪些能复用的东西，但 AI 能从主题清单里看出来。
    输出依然标记为待确认 —— AI 可能把普通代码说成"可复用方案"。
    """

    if len(theme_summaries) != len(themes):
        raise ValueError("theme_summaries must be parallel to themes")
    if not themes:
        return []

    lines = [
        f"- {summary.title}（{summary.kind}，{len(summary.sources)} 个来源）："
        f"{summary.summary}"
        for summary in theme_summaries
    ]
    prompt = (
        "This project was reviewed theme by theme:\n"
        + "\n".join(lines)
        + "\n\n"
        + ASSET_JSON_INSTRUCTION
    )
    data = complete_json_with_retry(client, prompt)

    raw = data.get("assets")
    if not isinstance(raw, list):
        raise LLMError('AssetSummary list requires an "assets" list')

    assets: list[AssetSummary] = []
    for item in raw:
        if not isinstance(item, dict):
            raise LLMError("each asset must be a JSON object")
        assets.append(AssetSummary.from_dict(item))
    return assets[: max(0, max_assets)]


def rule_based_summary(theme: Theme) -> ThemeSummary:
    """离线兜底：只依据 Git 事实描述一个主题。

    供 CLI 离线模式与确定性评测基线使用。
    """

    start = theme.started_at.date().isoformat()
    end = theme.ended_at.date().isoformat()
    number = theme.id.split("-")[-1] if "-" in theme.id else theme.id
    kind_zh = KIND_LABELS_ZH.get(theme.kind, theme.kind)
    summary = (
        f"共 {theme.commit_count} 次提交（{start} 至 {end}），"
        f"属于{kind_zh}类工作。"
    )
    return ThemeSummary(
        title=f"开发主题 {number}",
        kind=theme.kind,
        summary=summary,
        sources=theme.commit_hashes,
    )


def _commit_lines(commits: list[CommitEvent]) -> list[str]:
    ordered = sorted(commits, key=lambda event: event.committed_at)
    lines: list[str] = []
    for event in ordered:
        when = event.committed_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"{event.short_hash} ({when}) {event.message_subject}")
    return lines
