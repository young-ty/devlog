import { useState } from "react";

/** 论断的来源提交列表。
 *
 * 一条论断动辄挂在几十条提交上，全部铺开会把正文冲垮——成稿阅读里那种
 * 满屏 40 位 hash 的观感就是这么来的。所以收起时只给前几条短 hash
 * （够 `git show` 用，鼠标悬停能看到完整的），其余的折成一个可点的
 * 「等 N 个提交」。
 *
 * 成稿阅读和逐条校对共用这一份规则，免得两边各写一套、迟早长得不一样。
 */

const SHORT_LENGTH = 7;
const VISIBLE_WHEN_COLLAPSED = 3;

interface SourceListProps {
  sources: string[];
  /** 前缀文案，不用带冒号。 */
  label?: string;
}

export function SourceList({ sources, label = "来源提交" }: SourceListProps) {
  const [expanded, setExpanded] = useState(false);

  if (sources.length === 0) {
    return null;
  }

  const visible = expanded
    ? sources
    : sources.slice(0, VISIBLE_WHEN_COLLAPSED);
  const hidden = sources.length - visible.length;

  return (
    <span className="source-list">
      {label}：
      {visible.map((source) => (
        <code key={source} title={source}>
          {source.slice(0, SHORT_LENGTH)}
        </code>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="source-toggle"
          onClick={() => setExpanded(true)}
        >
          等 {sources.length} 个提交
        </button>
      )}
      {expanded && sources.length > VISIBLE_WHEN_COLLAPSED && (
        <button
          type="button"
          className="source-toggle"
          onClick={() => setExpanded(false)}
        >
          收起
        </button>
      )}
    </span>
  );
}
