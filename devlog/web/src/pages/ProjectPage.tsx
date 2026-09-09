import { useEffect, useState } from "react";
import {
  generateReview,
  getLLMConfig,
  listReviews,
  scanProject,
} from "../api";
import type { ReviewSummary } from "../types";
import { formatDateTime, formatRange } from "../utils";

interface ProjectPageProps {
  projectId: number;
  projectName: string;
  projectPath: string;
  onBack: () => void;
  onOpenTimeline: () => void;
  onOpenReview: (draftId: number) => void;
  onOpenNotes: () => void;
  onOpenBugs: () => void;
}

export function ProjectPage({
  projectId,
  projectName,
  projectPath,
  onBack,
  onOpenTimeline,
  onOpenReview,
  onOpenNotes,
  onOpenBugs,
}: ProjectPageProps) {
  const [reviews, setReviews] = useState<ReviewSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [llmReady, setLLMReady] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listReviews(projectId)
      .then((items) => {
        if (!cancelled) {
          setReviews(items);
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
  }, [projectId, reloadKey]);

  useEffect(() => {
    let cancelled = false;
    getLLMConfig()
      .then((config) => {
        if (!cancelled) {
          setLLMReady(config.configured);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLLMReady(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function handleScan(reset: boolean) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await scanProject(projectId, reset);
      setSuccess(
        `${reset ? "已重置并重新" : ""}扫描完成：共 ${result.total_events} 条提交，本次新写入 ${result.inserted_events} 条`,
      );
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerate() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await generateReview(projectId, true);
      setSuccess(
        `已生成草稿 #${result.draft_id}（离线模式）：${result.claim_count} 条论断、${result.question_count} 个引导问题`,
      );
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerateOnline() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await generateReview(projectId, false);
      setSuccess(
        `已生成 AI 草稿 #${result.draft_id}（中文摘要）：${result.claim_count} 条论断、${result.question_count} 个引导问题`,
      );
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const pendingCount = reviews.reduce(
    (sum, review) => sum + review.ai_pending_claims,
    0,
  );
  const confirmedCount = reviews.reduce(
    (sum, review) => sum + review.confirmed_claims,
    0,
  );
  const totalClaimCount = reviews.reduce(
    (sum, review) => sum + review.total_claims,
    0,
  );

  return (
    <main className="container">
      <div className="page-head">
        <button className="back-link" onClick={onBack}>
          ← 返回项目列表
        </button>
        <h1>{projectName}</h1>
        <p className="page-sub mono">{projectPath}</p>
      </div>

      {error && <p className="message error">{error}</p>}
      {success && <p className="message success">{success}</p>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">复盘草稿</div>
          <div className="stat-value">{reviews.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">全部论断</div>
          <div className="stat-value">{totalClaimCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">待确认</div>
          <div className="stat-value warning">{pendingCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">已确认</div>
          <div className="stat-value success">{confirmedCount}</div>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>数据与复盘</h2>
          <span className="panel-hint">生成草稿前先扫描，让数据保持最新</span>
        </div>
        <div className="actions">
          <button disabled={busy} onClick={() => handleScan(false)}>
            {busy ? "处理中…" : "扫描仓库"}
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => handleScan(true)}
          >
            重置并重扫
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={onOpenTimeline}
          >
            查看开发时间线
          </button>
          <button
            disabled={busy || llmReady === false}
            onClick={handleGenerateOnline}
          >
            {llmReady === null
              ? "检测 AI 配置…"
              : llmReady
                ? "生成中文复盘（AI）"
                : "AI 未配置"}
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={handleGenerate}
          >
            生成快速骨架（离线）
          </button>
        </div>
        {llmReady === false && (
          <p className="panel-hint" style={{ marginTop: 12 }}>
            AI 模式需要 DeepSeek key：在 ~/.devlog/config.toml 中填写
            api_key（或设置环境变量 DEEPSEEK_API_KEY）。
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>日常记忆</h2>
          <span className="panel-hint">
            开发中的随手记录与 Bug 现场，都是完工复盘的材料
          </span>
        </div>
        <div className="actions">
          <button onClick={onOpenNotes}>写每日复盘</button>
          <button className="secondary" onClick={onOpenBugs}>
            Bug 清单
          </button>
        </div>
      </section>

      <section className="section">
        <div className="panel-head">
          <h2>复盘草稿</h2>
          <span className="panel-hint">
            {loading
              ? "读取中…"
              : `${reviews.length} 份 · ${pendingCount} 条待确认`}
          </span>
        </div>

        {loading && (
          <>
            <div className="skeleton" />
            <div className="skeleton" />
          </>
        )}

        {!loading && reviews.length === 0 && (
          <div className="empty">
            <strong>还没有复盘草稿</strong>
            先扫描仓库，再点击“生成快速骨架（离线）”或“生成中文复盘（AI）”。
          </div>
        )}

        {reviews.map((review) => {
          const confirmedRatio =
            review.total_claims === 0
              ? 0
              : Math.round(
                  (review.confirmed_claims / review.total_claims) * 100,
                );
          return (
            <button
              key={review.draft_id}
              className="item-card"
              onClick={() => onOpenReview(review.draft_id)}
            >
              <div className="item-top">
                <div>
                  <div className="item-title">
                    草稿 #{review.draft_id}
                    {review.ai_pending_claims === 0 && (
                      <span className="badge badge-confirmed">已处理完</span>
                    )}
                  </div>
                  <div className="item-path">
                    {formatRange(
                      review.range_start,
                      review.range_end,
                    )}
                  </div>
                </div>
                <span className="arrow">→</span>
              </div>
              <div className="item-meta">
                <span>论断 {review.total_claims}</span>
                <span>待确认 {review.ai_pending_claims}</span>
                <span>已确认 {review.confirmed_claims}</span>
                <span>生成于 {formatDateTime(review.created_at)}</span>
              </div>
              <div className="progress">
                <div
                  className="progress-fill"
                  style={{ width: `${confirmedRatio}%` }}
                />
              </div>
            </button>
          );
        })}
      </section>
    </main>
  );
}
