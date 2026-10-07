import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icons";
import type { TimelineEvent } from "../types";
import { formatDate, formatDateTime, formatRange } from "../utils";

/** 时间线上的一个事件卡片。

 * 收起时标题和正文各截断两行，展开后完整显示；只有真的被截断的卡片才
 * 会出现"展开"入口 —— 点一下没有任何变化的假入口比没有入口更让人烦躁。
 */

interface TimelineEventCardProps {
  event: TimelineEvent;
  open: boolean;
  onToggle: () => void;
  /** 卡片高度上限，由时间线按几何算出来，保证展开后不会顶出可视区。 */
  maxHeight: number;
  /** 展开后追加的内容，例如批注列表和新增批注表单。 */
  children?: ReactNode;
}

interface CardContent {
  tone: string;
  icon: IconName;
  label: string;
  time: string;
  title: string;
  body: string;
  detail?: ReactNode;
}

const BUG_STATUS_LABELS: Record<string, string> = {
  open: "Bug 待排查",
  root_cause_found: "Bug 已定位",
  resolved: "Bug 已解决",
};

function describe(event: TimelineEvent): CardContent | null {
  if (event.kind === "commit" && event.commit) {
    const commit = event.commit;
    const translated = commit.translated_subject?.trim();
    return {
      tone: "commit",
      icon: "commit",
      label: commit.noise_type === "none" ? "提交" : `噪音 · ${commit.noise_type}`,
      time: formatDateTime(commit.committed_at),
      title: translated || commit.message_subject,
      body: `${commit.files_changed} 个文件 · +${commit.insertions} / -${commit.deletions}`,
      detail: translated ? <>原文：{commit.message_subject}</> : undefined,
    };
  }

  if (event.kind === "bug" && event.bug) {
    const bug = event.bug;
    return {
      tone: "bug",
      icon: "bug",
      label: BUG_STATUS_LABELS[bug.status] ?? "Bug",
      time: formatDateTime(bug.captured_at),
      title: bug.title || "（未命名 Bug）",
      body: bug.root_cause || bug.error_text.split("\n")[0] || "",
      detail: (
        <>
          {bug.error_text && <p className="tl-detail">报错：{bug.error_text}</p>}
          {bug.root_cause && <p className="tl-detail">根因：{bug.root_cause}</p>}
          {bug.solution && <p className="tl-detail">解法：{bug.solution}</p>}
        </>
      ),
    };
  }

  if (event.kind === "note" && event.note) {
    const note = event.note;
    return {
      tone: "note",
      icon: "note",
      label: "每日笔记",
      time: formatDate(note.note_date),
      title: note.summary || "（当天没有写总结）",
      body: note.issues ? `卡点：${note.issues}` : note.plan,
      detail:
        note.plan && note.issues ? <p className="tl-detail">下一步：{note.plan}</p> : undefined,
    };
  }

  if (event.kind === "annotation" && event.annotation) {
    const annotation = event.annotation;
    return {
      tone: "annotation",
      icon: "annotation",
      label: annotation.kind === "decision" ? "决策批注" : "备注批注",
      time: formatDateTime(event.at),
      title: annotation.body,
      body: `挂在提交 ${annotation.commit_hash.slice(0, 7)} 上`,
    };
  }

  if (event.kind === "milestone" && event.theme) {
    return {
      tone: "milestone",
      icon: "milestone",
      label: "里程碑候选",
      time: formatDateTime(event.theme.ended_at),
      title: event.theme.title,
      body: `${event.theme.commit_count} 个提交围绕这件事`,
    };
  }

  if (event.kind === "gap" && event.gap) {
    return {
      tone: "gap",
      icon: "gap",
      label: `空档 ${event.gap.days} 天`,
      time: formatRange(event.gap.started_at, event.gap.ended_at),
      title: "这段时间没有提交",
      body: "是暂停了、换方向了，还是在做不产生提交的工作？",
      detail: (
        <p className="tl-detail">
          从 {formatDateTime(event.gap.started_at)} 到{" "}
          {formatDateTime(event.gap.ended_at)} 之间没有有效提交。
        </p>
      ),
    };
  }

  return null;
}

function isClipped(node: HTMLElement | null): boolean {
  return node !== null && node.scrollHeight > node.clientHeight + 1;
}

export function TimelineEventCard({
  event,
  open,
  onToggle,
  maxHeight,
  children,
}: TimelineEventCardProps) {
  const titleRef = useRef<HTMLDivElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [clampable, setClampable] = useState(false);

  const content = describe(event);

  useLayoutEffect(() => {
    if (open) {
      // 展开状态下没有截断，量不出真实结果，保留收起时的判定。
      return;
    }
    setClampable(
      isClipped(titleRef.current) || isClipped(bodyRef.current),
    );
  }, [open, content?.title, content?.body]);

  if (!content) {
    return null;
  }

  const expandable = clampable || open;

  return (
    <article
      className={[
        "tl-card",
        `tl-card-${content.tone}`,
        open ? "tl-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={{ maxHeight }}
    >
      <div className="tl-card-head">
        <span className="tl-tag">
          <Icon name={content.icon} className="tl-tag-icon" />
          {content.label}
        </span>
        <span className="tl-time">{content.time}</span>
      </div>
      <div className="tl-title" ref={titleRef}>
        {content.title}
      </div>
      {content.body && (
        <div className="tl-body" ref={bodyRef}>
          {content.body}
        </div>
      )}
      {open && content.detail && (
        <div className="tl-extra">{content.detail}</div>
      )}
      {open && children}
      {expandable && (
        <button
          type="button"
          className="tl-more"
          aria-expanded={open}
          onClick={onToggle}
        >
          <span>{open ? "收起" : "展开"}</span>
          <Icon name="chevron" className="tl-chevron" />
        </button>
      )}
    </article>
  );
}
