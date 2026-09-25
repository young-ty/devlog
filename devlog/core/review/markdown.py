"""把 ReviewDraft 渲染成成稿 Markdown 并写入磁盘。

排版规则（章节顺序、哪些论断算数、空章节怎么提示）全部从 document 模块拿，
和界面里看到的成稿是同一份内容。规则各写一遍必然漂移，最后就会出现
"界面里看到的和导出的文件对不上"这种最难解释的问题。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from devlog.core.review.document import (
    EXTRA_SECTION,
    FinalClaim,
    FinalDocument,
    build_final_document,
    section_placeholder,
)
from devlog.core.review.models import ReviewDraft


# 章节图标在 Markdown 里只能用字符表示，名字跟界面同一套（Icons 的名字），
# 后端换图标时这里跟着换，不会各说各话。
SECTION_EMOJI = {
    "note": "📄",
    "commit": "🔀",
    "tag": "🏷️",
    "bug": "🐞",
    "warning": "⚠️",
    "star": "⭐",
    "help": "❓",
}
UNKNOWN_ICON = "•"

STATUS_LABELS = {
    "fact": "✅ 事实",
    "confirmed": "✔ 已确认",
    "edited": "✏️ 已修改",
    "ai_pending": "🤖 AI 推断 · 待确认",
}


class ReviewExportError(ValueError):
    """当复盘文档无法写入时抛出。"""


def _fmt_date(when: datetime) -> str:
    return when.strftime("%Y-%m-%d")


def _claim_line(claim: FinalClaim) -> str:
    sources = ""
    if claim.sources:
        shown = "、".join(f"`{source}`" for source in claim.sources[:3])
        if len(claim.sources) > 3:
            shown += f" 等 {len(claim.sources)} 个"
        sources = "（来源：" + shown + "）"

    label = STATUS_LABELS.get(claim.status, claim.status)
    note = f"（备注：{claim.user_note}）" if claim.user_note else ""
    return f"- {claim.text}{sources} · {label}{note}"


def _answer_lines(number: int, answer: str) -> list[str]:
    """把用户补充的回答渲染成列表项；多行回答要缩进，否则会撑破列表。"""

    head, *rest = answer.splitlines()
    lines = [f"- ✍️ 我的补充（第 {number} 问）：{head}"]
    lines.extend(f"  {line}" for line in rest)
    return lines


def _status_text(document: FinalDocument) -> str:
    if document.status == "finalized":
        stamp = (
            f"（{_fmt_date(document.finalized_at)}）"
            if document.finalized_at
            else ""
        )
        return f"已定稿{stamp}"
    if document.pending_count:
        return f"进行中 · 还有 {document.pending_count} 条 AI 推断未确认"
    return "进行中"


def _header_lines(document: FinalDocument) -> list[str]:
    """文首的定位信息：范围、状态、目录。"""

    toc = " · ".join(
        f"{SECTION_EMOJI.get(section.icon, UNKNOWN_ICON)} {section.title}"
        for section in document.sections
    )
    return [
        f"# 复盘：{document.project_name}",
        "",
        f"> 范围：{_fmt_date(document.range_start)} ~ {_fmt_date(document.range_end)}",
        f"> 生成于：{_fmt_date(document.generated_at)} · {_status_text(document)}",
        _scope_note(document),
        "",
        f"**目录**：{toc}",
        "",
    ]


def _scope_note(document: FinalDocument) -> str:
    """一句话说清"哪些内容算数"，这是这份文档最容易被误读的地方。"""

    if not document.pending_count:
        return "> 正文只收录你确认过的内容；AI 推断未经确认的一律不计入。"
    if document.status == "finalized":
        return (
            f"> 正文只收录你确认过的内容；另有 {document.pending_count} 条 AI 推断"
            "未经确认，因此不计入。"
        )
    return (
        f"> 正文只收录你确认过的内容；还有 {document.pending_count} 条 AI 推断"
        "待确认，列在文末。"
    )


def _section_hint(section, draft: ReviewDraft) -> str:
    """空板块的提示语。

    「其他补充」这一节没有对应的引导问题，用 document 里给它的说明；
    其余板块用共用规则找出"该回答第几问"。
    """

    if section.title == EXTRA_SECTION:
        return section.hint
    return section_placeholder(section.title, draft.questions)


def export_markdown(
    draft: ReviewDraft,
    *,
    status: str = "draft",
    finalized_at: datetime | None = None,
) -> str:
    """把草稿渲染成一份独立的成稿 Markdown。"""

    document = build_final_document(
        draft, status=status, finalized_at=finalized_at
    )
    lines = _header_lines(document)

    for section in document.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for claim in section.claims:
            lines.append(_claim_line(claim))
        for answer in section.answers:
            lines.extend(_answer_lines(answer.question_number, answer.answer))
        if section.is_empty:
            lines.append("> " + _section_hint(section, draft))
        lines.append("")

    # 已经回答过的问题，内容已经落到对应章节，这里只列还缺的部分，
    # 免得导出文档里出现一堆"问题 + 重复答案"。
    pending = [
        (number, question.text)
        for number, question in enumerate(draft.questions, start=1)
        if not question.answer.strip()
    ]
    if pending:
        lines.append("## 待补充的问题（人机共创）")
        lines.append("")
        for number, text in pending:
            lines.append(f"{number}. {text}")
        lines.append("")

    # 未确认的 AI 推断单独放文末：留着是给用户复查用的参考，
    # 但绝不能和正文混在一起，否则读的人分不清哪句是背过书的。
    if document.pending:
        lines.append("## 未确认的 AI 推断（不计入正文）")
        lines.append("")
        if document.status == "finalized":
            # 成稿是拿去归档和给别人看的，几十条 AI 猜测堆在后面会让人怀疑
            # 正文的可靠性。数量留在文末做交代，具体内容回界面逐条确认。
            lines.append(
                f"共 {len(document.pending)} 条 AI 推断未通过确认，未计入正文。"
                "它们仍保留在 DevLog 的草稿里，需要时回界面逐条确认。"
            )
        else:
            for claim in document.pending:
                lines.append(_claim_line(claim))
        lines.append("")

    lines.append("---")
    lines.append("_由 DevLog 生成。正文只收录已确认的内容。_")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(
    draft: ReviewDraft,
    target_path: str | Path,
    *,
    status: str = "draft",
    finalized_at: datetime | None = None,
) -> Path:
    """渲染草稿并写入 target_path（会自动创建父目录）。

    `status` / `finalized_at` 一并带上，导出文件才知道自己是不是成品：
    同一份草稿在定稿前后导出，文首的状态行必须跟着变。
    """

    return write_markdown_text(
        export_markdown(draft, status=status, finalized_at=finalized_at),
        target_path,
    )


def write_markdown_text(text: str, target_path: str | Path) -> Path:
    """把已经渲染好的 Markdown 文本写入 target_path。"""

    target = Path(target_path).expanduser()
    if target.is_dir():
        raise ReviewExportError(f"target is a directory, not a file: {target}")
    if not target.name or target.name in {".", ".."}:
        raise ReviewExportError("target path must name a file")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target.resolve()
