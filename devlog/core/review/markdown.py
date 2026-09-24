"""把 ReviewDraft 渲染为 Markdown 并写入磁盘。"""

from __future__ import annotations

from pathlib import Path

from devlog.core.review.models import (
    SECTION_ASSETS,
    SECTION_ISSUES,
    SECTION_ORDER,
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
)


STATUS_LABELS = {
    ClaimStatus.FACT: "✅ 事实",
    ClaimStatus.AI_PENDING: "🤖 AI 推断 · 待确认",
    ClaimStatus.CONFIRMED: "✔ 已确认",
    ClaimStatus.EDITED: "✏️ 已修改",
}

# 没有引导问题、也不会自动填充的板块，说明它的内容该从哪里来。
SECTION_HINTS = {
    SECTION_ISSUES: (
        "> 本板块由 Bug 捕获记录自动汇总。还没有内容时，"
        "用 Bug 捕获功能把报错、环境和 Git 状态存下来。"
    ),
    SECTION_ASSETS: (
        "> 本板块由 AI 横跨所有开发主题归纳，逐条确认之后才算数。"
    ),
}


class ReviewExportError(ValueError):
    """当复盘文档无法写入时抛出。"""


def _fmt_date(when) -> str:
    return when.strftime("%Y-%m-%d")


def _claim_line(claim: ReviewClaim) -> str:
    sources = ""
    if claim.sources:
        shown = "、".join(f"`{source}`" for source in claim.sources[:3])
        if len(claim.sources) > 3:
            shown += f" 等 {len(claim.sources)} 个"
        sources = "（来源：" + shown + "）"

    label = STATUS_LABELS.get(claim.status, claim.status.value)
    note = f"（备注：{claim.user_note}）" if claim.user_note else ""
    return f"- {claim.text}{sources} · {label}{note}"


def _section_placeholder(section: str, draft: ReviewDraft) -> str:
    """空板块的提示语：能指到具体问题就指过去，别只说"请回答文末问题"。"""

    for index, question in enumerate(draft.questions, start=1):
        if question.section == section:
            return f"> 本板块需要你补充：请回答文末第 {index} 个引导问题。"
    return SECTION_HINTS.get(section, "> 本板块暂无可自动填充的内容。")


def export_markdown(draft: ReviewDraft) -> str:
    """把草稿渲染成一份独立的 Markdown 文档。"""

    lines = [
        f"# 复盘：{draft.project_name}",
        "",
        f"> 范围：{_fmt_date(draft.range_start)} ~ {_fmt_date(draft.range_end)}",
        "> AI 生成的内容均为草稿，需人工逐条确认后生效。",
        "",
    ]

    for section in SECTION_ORDER:
        section_claims = [
            claim for claim in draft.claims if claim.section == section
        ]
        lines.append(f"## {section}")
        lines.append("")
        if section_claims:
            for claim in section_claims:
                lines.append(_claim_line(claim))
        else:
            lines.append(_section_placeholder(section, draft))
        lines.append("")

    if draft.questions:
        lines.append("## 待回答的问题（人机共创）")
        lines.append("")
        for index, question in enumerate(draft.questions, start=1):
            lines.append(f"{index}. {question.text}")
        lines.append("")

    lines.append("---")
    lines.append("_由 DevLog 生成。AI 推断仅作草稿，未经确认不得视为事实。_")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(draft: ReviewDraft, target_path: str | Path) -> Path:
    """渲染草稿并写入 target_path（会自动创建父目录）。"""

    target = Path(target_path).expanduser()
    if target.is_dir():
        raise ReviewExportError(f"target is a directory, not a file: {target}")
    if not target.name or target.name in {".", ".."}:
        raise ReviewExportError("target path must name a file")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(export_markdown(draft), encoding="utf-8")
    return target.resolve()
