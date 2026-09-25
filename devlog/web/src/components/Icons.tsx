/** 全站共用的线性描边图标。
 *
 * 统一 16x16 视箱、统一 1.6 描边、统一用 currentColor，颜色和大小交给
 * CSS。时间线节点、统计卡共用同一套，避免每个页面各画一份导致粗细和
 * 圆角对不上。
 */

export type IconName =
  | "commit"
  | "bug"
  | "note"
  | "annotation"
  | "milestone"
  | "gap"
  | "chevron"
  | "drag"
  | "clock"
  | "calendar"
  | "tag"
  | "layers"
  | "star"
  | "warning"
  | "help";

const PATHS: Record<IconName, string[]> = {
  commit: [
    "M11.2 8a3.2 3.2 0 1 1-6.4 0 3.2 3.2 0 0 1 6.4 0",
    "M8 1.2v3.6",
    "M8 11.2v3.6",
  ],
  bug: [
    "M5 8.6a3 3 0 0 1 3-3 3 3 0 0 1 3 3v.4a3 3 0 0 1-3 3 3 3 0 0 1-3-3z",
    "M5.2 7.2H2.6",
    "M10.8 7.2h2.6",
    "M5.2 10.6H2.6",
    "M10.8 10.6h2.6",
    "M6.1 5.6 5.1 3.9",
    "M9.9 5.6l1-1.7",
    "M8 5.6V2.9",
  ],
  note: [
    "M3 2.5h7.4L13.5 5.6v7.9H3z",
    "M10.2 2.6v3.1h3.1",
    "M5.2 8.6h5.6",
    "M5.2 11h4",
  ],
  annotation: [
    "M2.5 3.5h11v7h-6.2l-3 2.9v-2.9H2.5z",
    "M5.4 7h5.2",
  ],
  milestone: ["M4.2 2v12", "M4.2 3.2h8L10.6 5.8l1.6 2.6h-8"],
  gap: [
    "M9.9 8.4a1.9 1.9 0 1 1-3.8 0 1.9 1.9 0 0 1 3.8 0",
    "M2.4 8.4h2.2",
    "M11.4 8.4h2.2",
    "M8 6.5V3.2",
    "M6.8 4.4 8 3.2l1.2 1.2",
  ],
  chevron: ["M4 6.4 8 10.4l4-4"],
  drag: [
    "M8 2.6v10.8",
    "M2.6 8h10.8",
    "M8 2.6 6.5 4.2",
    "M8 2.6l1.5 1.6",
    "M8 13.4l-1.5-1.6",
    "M8 13.4l1.5-1.6",
    "M2.6 8 4.2 6.5",
    "M2.6 8l1.6 1.5",
    "M13.4 8l-1.6-1.5",
    "M13.4 8l-1.6 1.5",
  ],
  clock: [
    "M13.8 8a5.8 5.8 0 1 1-11.6 0 5.8 5.8 0 0 1 11.6 0",
    "M8 4.4V8l2.4 1.6",
  ],
  calendar: [
    "M3.8 3.4h8.4a1.4 1.4 0 0 1 1.4 1.4v7.4a1.4 1.4 0 0 1-1.4 1.4H3.8a1.4 1.4 0 0 1-1.4-1.4V4.8a1.4 1.4 0 0 1 1.4-1.4z",
    "M2.4 6.6h11.2",
    "M5.4 2.1v2.5",
    "M10.6 2.1v2.5",
  ],
  tag: [
    "M2.6 7.4V3.4a.8.8 0 0 1 .8-.8h4l6 6-4.8 4.8z",
    "M5.9 5.4a.5.5 0 1 1-1 0 .5.5 0 0 1 1 0",
  ],
  layers: [
    "M8 2 2.6 5 8 8l5.4-3z",
    "M2.6 8 8 11l5.4-3",
    "M2.6 11 8 14l5.4-3",
  ],
  // 成稿三个章节专用：可复用资产（星）、踩坑总结（警示）、遗留与下一步（问号）。
  star: [
    "M8 2.2 9.6 6l4 .3-3 2.6.9 3.9L8 10.9 4.5 12.8l.9-3.9-3-2.6 4-.3z",
  ],
  warning: ["M8 2.5 14 13H2z", "M8 6.4v3", "M8 11.4h.01"],
  help: [
    "M13.5 8a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0",
    "M6.4 6.4a1.7 1.7 0 1 1 2.2 1.7c-.4.2-.6.5-.6.9v.3",
    "M8 11.6h.01",
  ],
};

/** 图标名的运行时清单：后端给的章节图标是个字符串，得先验一下再用。 */
export const ICON_NAMES = Object.keys(PATHS) as IconName[];

export function isIconName(value: string): value is IconName {
  return (ICON_NAMES as string[]).includes(value);
}

export function Icon({
  name,
  className,
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
