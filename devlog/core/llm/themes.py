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
