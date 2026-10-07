import { useState } from "react";

import { Icon, isIconName } from "./Icons";
import { SourceList } from "./SourceList";
import type { ClaimStatus, FinalDocument, FinalSection } from "../types";

/** 成稿阅读视图。

 * 和「逐条校对」的分工：这里只负责把已经认过的内容排成一篇能读的文章，
 * 不提供编辑入口——读的时候手滑改坏一条论断，比少读一段糟糕得多。
 * 哪些内容算数由后端的成稿规则决定，这里不自己判断状态。
 */

const STATUS_LABELS: Record<ClaimStatus, string> = {
  fact: "事实",
  confirmed: "已确认",
  edited: "我改过",
  ai_pending: "未确认",
};

interface ReviewReadingViewProps {
  document: FinalDocument;
  /** 点了「去确认」时切到校对视图。 */
  onReviewPending: () => void;
}

function iconOf(section: FinalSection) {
  return isIconName(section.icon) ? section.icon : "note";
}

function anchorOf(section: FinalSection): string {
  return `rv-${section.title}`;
}

export function ReviewReadingView({
  document,
  onReviewPending,
}: ReviewReadingViewProps) {
  const [showPending, setShowPending] = useState(false);
  const [active, setActive] = useState(
    document.sections[0]?.title ?? "",
  );

  return (
    <div className="rv-layout">
      <nav className="rv-toc">
        <div className="rv-toc-title">章节</div>
        {document.sections.map((section) => (
          <a
            key={section.title}
            href={`#${anchorOf(section)}`}
            className={[
              active === section.title ? "on" : "",
              section.is_empty ? "rv-toc-empty" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => setActive(section.title)}
          >
            <Icon name={iconOf(section)} className="rv-ico" />
            <span className="rv-toc-label">{section.title}</span>
            {section.count > 0 && (
              <span className="rv-toc-count">{section.count}</span>
            )}
          </a>
        ))}
      </nav>

      <article className="rv-doc">
        {document.pending_count > 0 && (
          <div className="rv-pending-bar">
            <Icon name="warning" className="rv-ico" />
            <span>
              还有 {document.pending_count} 条 AI 推断没有确认，暂不计入成稿
            </span>
            <button type="button" onClick={() => setShowPending((v) => !v)}>
              {showPending ? "收起" : "展开查看"}
            </button>
          </div>
        )}

        {showPending && (
          <div className="rv-pending-list">
            {document.pending.map((claim) => (
              <div key={claim.text} className="rv-claim rv-claim-pending">
                <p>{claim.text}</p>
                <div className="rv-meta">
                  <span className="rv-chip rv-chip-ai">AI 推断</span>
                  {claim.sources.length > 0 && (
                    <SourceList sources={claim.sources} />
                  )}
                  <button
                    type="button"
                    className="rv-mini"
                    onClick={onReviewPending}
                  >
                    去确认
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {document.sections.map((section) => (
          <section
            key={section.title}
            id={anchorOf(section)}
            className="rv-section"
          >
            <h2>
              <Icon name={iconOf(section)} className="rv-ico rv-ico-head" />
              {section.title}
            </h2>

            {section.is_empty && (
              <p className="rv-hint">{section.hint}</p>
            )}

            {section.claims.map((claim) => (
              <div key={claim.text} className="rv-claim">
                <p>{claim.text}</p>
                <div className="rv-meta">
                  <span
                    className={`rv-chip rv-chip-${claim.status}`}
                  >
                    {STATUS_LABELS[claim.status] ?? claim.status}
                  </span>
                  {claim.sources.length > 0 && (
                    <SourceList sources={claim.sources} />
                  )}
                  {claim.user_note && (
                    <span className="rv-note">备注：{claim.user_note}</span>
                  )}
                </div>
              </div>
            ))}

            {section.answers.map((answer) => (
              <div className="rv-qa" key={answer.question_number}>
                <p className="rv-q">
                  <Icon name="help" className="rv-ico" />
                  {answer.question}
                </p>
                <p className="rv-a">{answer.answer}</p>
              </div>
            ))}

            {section.open_questions.length > 0 && (
              <p className="rv-open">
                这一章还有 {section.open_questions.length} 个问题没回答
                <button
                  type="button"
                  className="rv-mini"
                  onClick={onReviewPending}
                >
                  去补充
                </button>
              </p>
            )}
          </section>
        ))}
      </article>
    </div>
  );
}
