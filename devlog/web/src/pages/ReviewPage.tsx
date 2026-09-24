import { useEffect, useState } from "react";
import { confirmClaims, exportReview, getReviewDraft } from "../api";
import type { ReviewDraft } from "../types";
import { ClaimCard } from "../components/ClaimCard";
import { formatDateTime, formatRange } from "../utils";

interface ReviewPageProps {
  draftId: number;
  onBack: () => void;
}

export function ReviewPage({ draftId, onBack }: ReviewPageProps) {
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getReviewDraft(draftId)
      .then((item) => {
        if (!cancelled) {
          setDraft(item);
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

  const sections: string[] = [];
  for (const claim of draft.claims) {
    if (!sections.includes(claim.section)) {
      sections.push(claim.section);
    }
  }

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

      <section className="panel">
        <div className="panel-head">
          <h2>确认进度</h2>
          <span className="panel-hint">
            {doneRatio}% 已完成 · 建议逐条阅读后再导出
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
          <button
            className="secondary"
            disabled={busy}
            onClick={handleExport}
          >
            导出 Markdown
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
            {claims.map((claim) => (
              <ClaimCard
                key={claim.id}
                claim={claim}
                onConfirm={confirmOne}
              />
            ))}
          </section>
        );
      })}

      {draft.questions.length > 0 && (
        <section className="section">
          <div className="panel-head">
            <h2>留给你思考的问题</h2>
            <span className="panel-hint">AI 无法从 Git 中推断的部分</span>
          </div>
          <div className="panel questions">
            <ol>
              {draft.questions.map((question, index) => (
                <li key={index}>
                  {question.text}
                  {question.section && (
                    <span className="question-section">
                      对应板块：{question.section}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </section>
      )}
    </main>
  );
}
