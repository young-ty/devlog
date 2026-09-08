"""Structured theme summaries produced through the LLM client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from devlog.core.git_source.models import CommitEvent
from devlog.core.llm.base import LLMClientBase, LLMError
from devlog.core.theming.models import Theme


THEME_JSON_INSTRUCTION = (
    "Return a JSON object only, with exactly these keys: "
    '"title" (short Chinese title), "kind" (feature/bugfix/refactor/docs/'
    'test/perf/build/other), "summary" (Chinese, 3-5 sentences, grounded '
    'in the commits), and "sources" (list of commit hashes you relied on).'
)


@dataclass(frozen=True)
class ThemeSummary:
    """Validated structured output for one theme."""

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
    """Ask for JSON, retry once with a hint, then degrade to an error."""

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
    """Produce a validated structured summary for one theme."""

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
    """Offline fallback: describe a theme from Git facts only.

    Used by the CLI offline mode and by the deterministic eval baseline.
    """

    start = theme.started_at.date().isoformat()
    end = theme.ended_at.date().isoformat()
    summary = (
        f"共 {theme.commit_count} 次提交（{start} 至 {end}），"
        f"类型为 {theme.kind}。"
    )
    return ThemeSummary(
        title=theme.title,
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
