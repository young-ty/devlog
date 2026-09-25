import { useEffect, useMemo, useRef, useState } from "react";

import { AnnotationPanel } from "./AnnotationPanel";
import { Icon } from "./Icons";
import { TimelineEventCard } from "./TimelineEventCard";
import { useDragPan } from "../hooks/useDragPan";
import type {
  AnnotationKind,
  CommitAnnotation,
  TimelineEvent,
  TimelineEventKind,
} from "../types";

/** 横向曲线时间线。

 * 事件等距排布，不按真实时间比例：一次三天停工会把按比例的轴撑出一大段
 * 空白，而密集交付日会挤成一条黑线。时间信息改由"空档节点"显式承载。
 *
 * 高度全部锁死：轨道 600px 从不变化，曲线画布固定下移 100px 预留出展开
 * 空间。代价是收起状态下上下各留一片空白，换来的是点开卡片时页面不跳。
 */

const PADX = 120;
const GAPX = 210;
// 空档节点左右放宽一点，让"这里停了一段时间"在视觉上就能看出来。
const GAP_WIDE = 300;
const MID = 200;
const AMP = 60;
const CANVAS_HEIGHT = 400;
const RAIL_HEIGHT = 600;
const OFFSET = 100;
const CARD_HALF = 93;

const FILTERS: Array<{ value: "all" | TimelineEventKind; label: string }> = [
  { value: "all", label: "全部" },
  { value: "commit", label: "提交" },
  { value: "bug", label: "Bug" },
  { value: "note", label: "笔记" },
  { value: "annotation", label: "批注" },
  { value: "milestone", label: "里程碑" },
  { value: "gap", label: "空档" },
];

interface TimelineRailProps {
  events: TimelineEvent[];
  truncatedCount: number;
  orphanAnnotationCount: number;
  annotations: Record<string, CommitAnnotation[]>;
  annotationBusy: boolean;
  onAddAnnotation: (
    commitHash: string,
    kind: AnnotationKind,
    body: string,
  ) => void;
  onDeleteAnnotation: (annotation: CommitAnnotation) => void;
}

interface Point {
  x: number;
  y: number;
}

/** 用 Catmull-Rom 转三次贝塞尔，把节点连成一条平滑曲线。 */
function buildCurve(points: Point[]): string {
  if (points.length === 0) {
    return "";
  }
  if (points.length === 1) {
    return `M ${points[0].x} ${points[0].y}`;
  }
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const previous = points[index - 1] ?? points[index];
    const current = points[index];
    const next = points[index + 1];
    const after = points[index + 2] ?? next;
    const c1x = current.x + (next.x - previous.x) / 6;
    const c1y = current.y + (next.y - previous.y) / 6;
    const c2x = next.x - (after.x - current.x) / 6;
    const c2y = next.y - (after.y - current.y) / 6;
    path += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${next.x} ${next.y}`;
  }
  return path;
}


export function TimelineRail({
  events,
  truncatedCount,
  orphanAnnotationCount,
  annotations,
  annotationBusy,
  onAddAnnotation,
  onDeleteAnnotation,
}: TimelineRailProps) {
  const [filter, setFilter] = useState<"all" | TimelineEventKind>("all");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [metrics, setMetrics] = useState({ left: 0, width: 0, total: 0 });
  const minimapRef = useRef<HTMLDivElement | null>(null);

  const { ref: viewportRef, dragging } = useDragPan<HTMLDivElement>();

  const points = useMemo(() => {
    let cursor = PADX;
    return events.map((event, index) => {
      if (index > 0) {
        cursor += event.kind === "gap" ? GAP_WIDE : GAPX;
      }
      return {
        x: cursor,
        y: MID + AMP * Math.sin((index * Math.PI) / 2),
      };
    });
  }, [events]);

  const totalWidth =
    points.length > 0 ? points[points.length - 1].x + PADX : 0;
  const curve = useMemo(() => buildCurve(points), [points]);

  // 每个筛选项显示实际数量：切到一条都没有的类型时（比如仓库里根本没
  // 抓过 Bug），卡片会全部变淡，没有数字的话用户会以为界面坏了。
  const kindCounts = useMemo(() => {
    const counts = new Map<TimelineEventKind, number>();
    events.forEach((event) => {
      counts.set(event.kind, (counts.get(event.kind) ?? 0) + 1);
    });
    return counts;
  }, [events]);

  // 缩略导航和两侧渐隐都要知道当前滚到哪、一屏多宽。
  useEffect(() => {
    const node = viewportRef.current;
    if (!node) {
      return;
    }
    function sync() {
      const target = viewportRef.current;
      if (!target) {
        return;
      }
      setMetrics({
        left: target.scrollLeft,
        width: target.clientWidth,
        total: target.scrollWidth,
      });
    }
    sync();
    node.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    return () => {
      node.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [viewportRef, totalWidth]);

  function jumpTo(clientX: number) {
    const node = viewportRef.current;
    const track = minimapRef.current;
    if (!node || !track) {
      return;
    }
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(
      1,
      Math.max(0, (clientX - rect.left) / rect.width),
    );
    node.scrollLeft = ratio * node.scrollWidth - node.clientWidth / 2;
  }

  // 展开一张卡片时，如果它有大半滑出了可视区，就把它拉回来。
  function ensureVisible(index: number) {
    const node = viewportRef.current;
    if (!node) {
      return;
    }
    const left = points[index].x - CARD_HALF;
    const right = points[index].x + CARD_HALF;
    if (left < node.scrollLeft + 12) {
      node.scrollTo({ left: left - 12, behavior: "smooth" });
    } else if (right > node.scrollLeft + node.clientWidth - 12) {
      node.scrollTo({
        left: right - node.clientWidth + 12,
        behavior: "smooth",
      });
    }
  }

  function toggleEvent(index: number) {
    const key = events[index].key;
    setOpenKey((current) => {
      const next = current === key ? null : key;
      if (next !== null) {
        ensureVisible(index);
      }
      return next;
    });
  }

  const canScrollLeft = metrics.left > 4;
  const canScrollRight =
    metrics.total > 0 && metrics.left < metrics.total - metrics.width - 4;
  const visibleRatio =
    metrics.total > 0 ? (metrics.width / metrics.total) * 100 : 100;
  const maxLeft = Math.max(0, metrics.total - metrics.width);
  const thumbLeft =
    maxLeft > 0 ? (metrics.left / maxLeft) * (100 - visibleRatio) : 0;

  return (
    <section className="panel tl-panel">
      <div className="panel-head tl-head">
        <h2>开发时间线</h2>
        <span className="panel-hint">
          {events.length} 个事件
          {truncatedCount > 0 && ` · 更早的 ${truncatedCount} 个未显示`}
        </span>
        <div className="tl-chips">
          {FILTERS.map((item) => {
            const count =
              item.value === "all"
                ? events.length
                : (kindCounts.get(item.value) ?? 0);
            return (
              <button
                key={item.value}
                type="button"
                className={[
                  "tl-chip",
                  filter === item.value ? "on" : "",
                  count === 0 ? "tl-chip-empty" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                title={
                  count === 0 ? `这个仓库还没有${item.label}事件` : undefined
                }
                onClick={() => setFilter(item.value)}
              >
                {item.label}
                <span className="tl-chip-count">{count}</span>
              </button>
            );
          })}
        </div>
        <span className="tl-drag-hint">
          <Icon name="drag" className="tl-drag-icon" />
          按住左键拖动 · 点卡片展开
        </span>
      </div>

      {events.length === 0 ? (
        <p className="panel-hint tl-empty">
          还没有可以画到时间线上的事件，先扫描一次仓库。
        </p>
      ) : (
        <>
          <div className="tl-viewport-wrap">
            <div
              className={`tl-viewport${dragging ? " tl-dragging" : ""}`}
              ref={viewportRef}
            >
              <div
                className="tl-rail"
                style={{ width: totalWidth, height: RAIL_HEIGHT }}
              >
                <div
                  className="tl-canvas"
                  style={{
                    top: OFFSET,
                    width: totalWidth,
                    height: CANVAS_HEIGHT,
                  }}
                >
                  <svg
                    className="tl-curve"
                    width={totalWidth}
                    height={CANVAS_HEIGHT}
                    viewBox={`0 0 ${totalWidth} ${CANVAS_HEIGHT}`}
                    aria-hidden="true"
                  >
                    <path d={curve} />
                  </svg>
                  {events.map((event, index) => {
                    const point = points[index];
                    const dim = filter !== "all" && event.kind !== filter;
                    return (
                      <div
                        key={event.key}
                        className={[
                          "tl-node",
                          `tl-node-${event.kind}`,
                          index % 2 === 1 ? "tl-below" : "tl-above",
                          dim ? "tl-dim" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        style={{ left: point.x, top: point.y }}
                      >
                        <span className="tl-dot" />
                        <TimelineEventCard
                          event={event}
                          open={openKey === event.key}
                          onToggle={() => toggleEvent(index)}
                          maxHeight={
                            index % 2 === 1
                              ? RAIL_HEIGHT - OFFSET - point.y - 26
                              : OFFSET + point.y - 26
                          }
                        >
                          {event.kind === "commit" && event.commit && (
                            <AnnotationPanel
                              commitHash={event.commit.hash}
                              annotations={
                                annotations[event.commit.hash] ?? []
                              }
                              busy={annotationBusy}
                              onAdd={onAddAnnotation}
                              onDelete={onDeleteAnnotation}
                            />
                          )}
                        </TimelineEventCard>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
            <div
              className={`tl-fade tl-fade-left${canScrollLeft ? " show" : ""}`}
            />
            <div
              className={`tl-fade tl-fade-right${canScrollRight ? " show" : ""}`}
            />
          </div>

          <div className="tl-foot">
            <div className="tl-legend">
              {FILTERS.filter((item) => item.value !== "all").map((item) => (
                <span
                  key={item.value}
                  className={`tl-legend-item tl-node-${item.value}`}
                >
                  <i />
                  {item.label}
                </span>
              ))}
            </div>
            <div className="tl-minimap">
              <div
                className="tl-mm-track"
                ref={minimapRef}
                onMouseDown={(event) => {
                  event.preventDefault();
                  jumpTo(event.clientX);
                }}
                onMouseMove={(event) => {
                  if (event.buttons === 1) {
                    jumpTo(event.clientX);
                  }
                }}
              >
                {events.map((event, index) => (
                  <span
                    key={event.key}
                    className={[
                      "tl-mm-dot",
                      `tl-node-${event.kind}`,
                      filter !== "all" && event.kind !== filter
                        ? "tl-dim"
                        : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    style={{
                      left: `${(points[index].x / totalWidth) * 100}%`,
                    }}
                  />
                ))}
                <span
                  className="tl-mm-view"
                  style={{
                    left: `${thumbLeft}%`,
                    width: `${visibleRatio}%`,
                  }}
                />
              </div>
              <div className="tl-mm-note">
                缩略导航 · 点一下跳到那个位置
              </div>
            </div>
          </div>
        </>
      )}

      {orphanAnnotationCount > 0 && (
        <p className="panel-hint tl-orphan-hint">
          另有 {orphanAnnotationCount} 条批注找不到对应的提交（历史被改写），
          已单独列在下方「孤儿批注」里。
        </p>
      )}
    </section>
  );
}
