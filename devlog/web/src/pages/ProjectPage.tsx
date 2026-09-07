import { useEffect, useState } from "react";
import { generateReview, listReviews, scanProject } from "../api";
import type { ReviewSummary } from "../types";

interface ProjectPageProps {
  projectId: number;
  projectName: string;
  onBack: () => void;
  onOpenReview: (draftId: number) => void;
}

export function ProjectPage({
  projectId,
  projectName,
  onBack,
  onOpenReview,
}: ProjectPageProps) {
  const [reviews, setReviews] = useState<ReviewSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listReviews(projectId)
      .then((items) => {
        if (!cancelled) {
          setReviews(items);
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
  }, [projectId, reloadKey]);

  async function handleScan(reset: boolean) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await scanProject(projectId, reset);
      setMessage(
        `${reset ? "已重置并" : ""}扫描完成：共 ${result.total_events} 条提交，新写入 ${result.inserted_events} 条`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerate() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await generateReview(projectId, true);
      setMessage(
        `已生成草稿 #${result.draft_id}（离线模式），共 ${result.claim_count} 条论断。`,
      );
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <button className="link-button" onClick={onBack}>
        ← 返回项目列表
      </button>
      <h1>{projectName}</h1>
      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      <section className="card actions">
        <button disabled={busy} onClick={() => handleScan(false)}>
          扫描仓库
        </button>
        <button disabled={busy} onClick={() => handleScan(true)}>
          重置并重扫
        </button>
        <button disabled={busy} onClick={handleGenerate}>
          生成复盘草稿（离线）
        </button>
      </section>

      <section>
        <h2>复盘草稿</h2>
        {loading && <p>加载中…</p>}
        {!loading && reviews.length === 0 && (
          <p>还没有草稿。先点上方"生成复盘草稿（离线）"。</p>
        )}
        {reviews.map((review) => (
          <button
            key={review.draft_id}
            className="project-row"
            onClick={() => onOpenReview(review.draft_id)}
          >
            <strong>草稿 #{review.draft_id}</strong>
            <span className="muted">
              {review.range_start.slice(0, 10)} ~ {review.range_end.slice(0, 10)}
              {" · "}
              论断 {review.total_claims}（待确认 {review.ai_pending_claims}，已确认{" "}
              {review.confirmed_claims}）
            </span>
          </button>
        ))}
      </section>
    </main>
  );
}
