import { useEffect, useState } from "react";
import { confirmClaims, exportReview, getReviewDraft } from "../api";
import type { ReviewDraft } from "../types";
import { ClaimCard } from "../components/ClaimCard";

interface ReviewPageProps {
  draftId: number;
  onBack: () => void;
}

export function ReviewPage({ draftId, onBack }: ReviewPageProps) {
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getReviewDraft(draftId)
      .then((item) => {
        if (!cancelled) {
          setDraft(item);
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
    try {
      const result = await confirmClaims(draftId, { claimIds: [claimId], note });
      setMessage(`已确认，剩余 ${result.remaining_pending} 条待确认。`);
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
    try {
      const result = await confirmClaims(draftId, { all: true });
      setMessage(`已确认 ${result.changed} 条。`);
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
    try {
      const result = await exportReview(draftId);
      setMessage(`已导出：${result.path}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <main className="container">加载中…</main>;
  }

  if (!draft) {
    return (
      <main className="container">
        <p className="error">{error || "草稿不存在"}</p>
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

  return (
    <main className="container">
      <button className="link-button" onClick={onBack}>
        ← 返回项目
      </button>
      <h1>复盘草稿 #{draft.draft_id}</h1>
      <p className="muted">
        {draft.range_start.slice(0, 10)} ~ {draft.range_end.slice(0, 10)}
      </p>
      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      <section className="card actions">
        <button disabled={busy || pendingCount === 0} onClick={confirmAll}>
          全部确认（{pendingCount}）
        </button>
        <button disabled={busy} onClick={handleExport}>
          导出 Markdown
        </button>
      </section>

      {sections.map((section) => (
        <section key={section} className="section">
          <h2>{section}</h2>
          {draft.claims
            .filter((claim) => claim.section === section)
            .map((claim) => (
              <ClaimCard
                key={claim.id}
                claim={claim}
                onConfirm={confirmOne}
              />
            ))}
        </section>
      ))}

      {draft.questions.length > 0 && (
        <section className="section">
          <h2>待回答的问题（人机共创）</h2>
          <ol>
            {draft.questions.map((question, index) => (
              <li key={index}>{question}</li>
            ))}
          </ol>
        </section>
      )}
    </main>
  );
}
