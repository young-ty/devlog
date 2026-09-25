import { useEffect, useState } from "react";
import {
  confirmClaims,
  exportReview,
  getReviewDocument,
  getReviewDraft,
  saveAnswer,
} from "../api";
import type { FinalDocument, ReviewDraft } from "../types";
import { ClaimCard } from "../components/ClaimCard";
import { Icon } from "../components/Icons";
import { ReviewReadingView } from "../components/ReviewReadingView";
import { formatDateTime, formatRange } from "../utils";

interface ReviewPageProps {
  draftId: number;
  onBack: () => void;
}

// 板块的固定展示顺序。AI 这次没产出内容的板块也保留位置：
// 用户需要分清"功能压根没跑"和"跑了但没找到候选"。
const SECTION_ORDER = [
  "项目概述",
  "开发时间线",
  "技术决策记录",
  "问题与解决",
  "踩坑总结",
  "可复用资产",
  "遗留与下一步",
];

function emptySectionHint(section: string, generationMode: string): string {
  if (section === "可复用资产") {
    if (generationMode === "offline") {
      return "离线模式不做可复用资产归纳；用「生成中文复盘（AI）」可以额外归纳跨主题的候选。";
    }
    return "本次 AI 归纳没有找到值得沉淀为可复用资产的候选。";
  }
  return "本次生成没有产出这一类内容，可以参考下方的引导问题补充。";
}

export function ReviewPage({ draftId, onBack }: ReviewPageProps) {
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  // 成稿是从后端拿的一份排好版的数据，前端不再自己判断哪条论断算数。
  const [finalDoc, setFinalDoc] = useState<FinalDocument | null>(null);
  // 默认进阅读视图：复盘首先是拿来读的，逐条校对是过程而不是结果。
  const [view, setView] = useState<"read" | "proof">("read");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  // 未保存的输入草稿，键是问题编号（从 1 开始）。
  const [answerDrafts, setAnswerDrafts] = useState<Record<number, string>>(
    {},
  );
  const [savingNumber, setSavingNumber] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getReviewDraft(draftId), getReviewDocument(draftId)])
      .then(([item, document]) => {
        if (!cancelled) {
          setDraft(item);
          setFinalDoc(document);
          setError("");
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [draftId, reloadKey]);

  async function confirmOne(claimId: number, note?: string) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await confirmClaims(draftId, {
        claimIds: [claimId],
        note,
      });
      if (result.remaining_pending === 0) {
        setSuccess("全部 AI 论断都已确认，可以导出了。");
      } else {
        setSuccess(`已确认这条，还剩 ${result.remaining_pending} 条待确认。`);
      }
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmAll() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await confirmClaims(draftId, { all: true });
      setSuccess(`已确认 ${result.changed} 条 AI 论断。`);
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleExport() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await exportReview(draftId);
      setSuccess(`已导出 Markdown：${result.path}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveAnswer(number: number) {
    const value = answerDrafts[number];
    if (value === undefined) {
      return;
    }
    setSavingNumber(number);
    setError("");
    setSuccess("");
    try {
      const updated = await saveAnswer(draftId, number, value);
      setDraft((current) =>
        current
          ? {
              ...current,
              questions: current.questions.map((question, index) =>
                index === number - 1 ? updated : question,
              ),
            }
          : current,
      );
      setAnswerDrafts((current) => {
        const next = { ...current };
        delete next[number];
        return next;
      });
      setSuccess(
        `已保存第 ${number} 个问题的回答，导出时会写进「${updated.section || "复盘文档"}」。`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingNumber(null);
    }
  }

  if (loading) {
    return (
      <main className="container">
        <div className="skeleton" />
        <div className="skeleton" />
        <div className="skeleton" />
      </main>
    );
  }

  if (!draft) {
    return (
      <main className="container">
        <p className="message error">{error || "草稿不存在"}</p>
      </main>
    );
  }

  const sections: string[] = [...SECTION_ORDER];
  for (const claim of draft.claims) {
    if (!sections.includes(claim.section)) {
      sections.push(claim.section);
    }
  }
  // 历史草稿没有资产归纳这一步，空板块不逐个占位（否则满屏都是空的），
  // 改成页面顶部一条整体说明。
  const showEmptySections = draft.generation_mode !== "unknown";

  const answeredCount = draft.questions.filter(
    (question) => question.answer.trim() !== "",
  ).length;

  const pendingCount = draft.claims.filter(
    (claim) => claim.status === "ai_pending",
  ).length;
  const confirmedCount = draft.claims.filter(
    (claim) => claim.status === "confirmed",
  ).length;
  const factCount = draft.claims.filter(
    (claim) => claim.status === "fact",
  ).length;
  const editedCount = draft.claims.filter(
    (claim) => claim.status === "edited",
  ).length;
  const total = draft.claims.length;
  const doneRatio = total === 0 ? 0 : Math.round(((total - pendingCount) / total) * 100);

  return (
    <main className="container">
      <div className="page-head">
        <button className="back-link" onClick={onBack}>
          ← 返回项目
        </button>
        <h1>复盘草稿 #{draft.draft_id}</h1>
        <p className="page-sub">
          {draft.project_name} ·{" "}
          {formatRange(draft.range_start, draft.range_end)} · 生成于{" "}
          {formatDateTime(draft.generated_at)}
        </p>
      </div>

      {error && <p className="message error">{error}</p>}
      {success && <p className="message success">{success}</p>}

      {draft.generation_mode === "unknown" && (
        <section className="panel">
          <p className="panel-hint">
            这份草稿由旧版本生成：不包含「可复用资产」归纳，模板问题也可能是旧的。
            用项目页的「生成中文复盘（AI）」重新生成，即可得到新版结构。
          </p>
        </section>
      )}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">论断总数</div>
          <div className="stat-value">{total}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">AI 待确认</div>
          <div className="stat-value warning">{pendingCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">已确认 / 已修改</div>
          <div className="stat-value success">
            {confirmedCount + editedCount}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">事实条目</div>
          <div className="stat-value accent">{factCount}</div>
        </div>
      </div>

      <div className="rv-toolbar">
        <div className="rv-seg">
          <button
            type="button"
            className={view === "read" ? "on" : ""}
            onClick={() => setView("read")}
          >
            <Icon name="note" className="rv-ico" />
            成稿阅读
          </button>
          <button
            type="button"
            className={view === "proof" ? "on" : ""}
            onClick={() => setView("proof")}
          >
            <Icon name="annotation" className="rv-ico" />
            逐条校对
            {pendingCount > 0 && <em>{pendingCount}</em>}
          </button>
        </div>
        <div className="rv-toolbar-spacer" />
        <button className="secondary" disabled={busy} onClick={handleExport}>
          导出 Markdown（可选）
        </button>
      </div>

      {view === "read" &&
        (finalDoc ? (
          <ReviewReadingView
            document={finalDoc}
            onReviewPending={() => setView("proof")}
          />
        ) : (
          <p className="panel-hint">正在整理成稿…</p>
        ))}

      {view === "proof" && (
        <>
      <section className="panel">
        <div className="panel-head">
          <h2>确认进度</h2>
          <span className="panel-hint">
            {doneRatio}% 已完成 · 确认过的内容才会进成稿
          </span>
        </div>
        <div className="progress">
          <div
            className="progress-fill"
            style={{ width: `${doneRatio}%` }}
          />
        </div>
        <div className="actions" style={{ marginTop: 14 }}>
          <button
            disabled={busy || pendingCount === 0}
            onClick={confirmAll}
          >
            全部确认（{pendingCount}）
          </button>
        </div>
        {draft.exported_path && (
          <p className="panel-hint" style={{ marginTop: 12 }}>
            上次导出：<span className="mono">{draft.exported_path}</span>
          </p>
        )}
      </section>

      {sections.map((section) => {
        const claims = draft.claims.filter(
          (claim) => claim.section === section,
        );
        if (claims.length === 0 && !showEmptySections) {
          return null;
        }
        const sectionPending = claims.filter(
          (claim) => claim.status === "ai_pending",
        ).length;
        return (
          <section key={section} className="section">
            <div className="panel-head">
              <h2>{section}</h2>
              <span className="panel-hint">
                {claims.length} 条
                {sectionPending > 0 ? ` · ${sectionPending} 条待确认` : ""}
              </span>
            </div>
            {claims.length === 0 ? (
              <p className="panel-hint">
                {emptySectionHint(section, draft.generation_mode)}
              </p>
            ) : (
              claims.map((claim) => (
                <ClaimCard
                  key={claim.id}
                  claim={claim}
                  onConfirm={confirmOne}
                />
              ))
            )}
          </section>
        );
      })}

      {draft.questions.length > 0 && (
        <section className="section">
          <div className="panel-head">
            <h2>留给你思考的问题</h2>
            <span className="panel-hint">
              已补充 {answeredCount}/{draft.questions.length} · 回答会写进对应板块
            </span>
          </div>
          <div className="panel questions">
            {draft.questions.map((question, index) => {
              const number = index + 1;
              const value = answerDrafts[number] ?? question.answer;
              const dirty = value !== question.answer;
              return (
                <article key={number} className="question-card">
                  <div className="question-head">
                    <span className="question-index">{number}</span>
                    <div>
                      <p className="question-text">{question.text}</p>
                      {question.section && (
                        <span className="question-section">
                          回答会写进「{question.section}」
                        </span>
                      )}
                    </div>
                  </div>
                  <textarea
                    rows={3}
                    placeholder="在这里写下你的补充，比如当时的取舍、踩到坑的位置…"
                    value={value}
                    onChange={(event) =>
                      setAnswerDrafts((current) => ({
                        ...current,
                        [number]: event.target.value,
                      }))
                    }
                  />
                  <div className="question-actions">
                    <button
                      className="secondary"
                      disabled={!dirty || busy || savingNumber !== null}
                      onClick={() => handleSaveAnswer(number)}
                    >
                      {savingNumber === number ? "保存中…" : "保存回答"}
                    </button>
                    {!dirty && question.answer.trim() !== "" && (
                      <span className="question-saved">已保存</span>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}
        </>
      )}
    </main>
  );
}
