import { useEffect, useState } from "react";
import {
  addAnnotation,
  deleteAnnotation,
  getLLMConfig,
  getProjectTimeline,
  getProjectTimelineEvents,
  listAnnotations,
  translateProjectCommits,
} from "../api";
import { AnnotationPanel } from "../components/AnnotationPanel";
import { Icon } from "../components/Icons";
import { TimelineRail } from "../components/TimelineRail";
import type {
  AnnotationKind,
  CommitAnnotation,
  ProjectTimeline,
  TimelineCommit,
  TimelineStream,
  TimelineTheme,
} from "../types";
import { formatDateTime, formatRange } from "../utils";

interface TimelinePageProps {
  projectId: number;
  projectName: string;
  projectPath: string;
  /** 设置里存完密钥后 +1，用来触发重新读一次 AI 配置。 */
  llmVersion: number;
  onOpenSettings: () => void;
  onBack: () => void;
}

const KIND_LABELS: Record<string, string> = {
  feature: "功能开发",
  bugfix: "问题修复",
  refactor: "重构",
  docs: "文档",
  test: "测试",
  perf: "性能",
  build: "构建",
  other: "其他",
};

const NOISE_LABELS: Record<string, string> = {
  merge: "合并提交",
  revert: "回滚",
  wip: "WIP",
  chore: "杂项",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

function noiseLabel(type: string): string {
  return NOISE_LABELS[type] ?? "噪音提交";
}

function themeNumber(theme: TimelineTheme): string {
  return theme.id.split("-").pop() ?? theme.id;
}

export function TimelinePage({
  projectId,
  projectName,
  projectPath,
  llmVersion,
  onOpenSettings,
  onBack,
}: TimelinePageProps) {
  const [timeline, setTimeline] = useState<ProjectTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [translating, setTranslating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [llmReady, setLLMReady] = useState<boolean | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [annotations, setAnnotations] = useState<
    Record<string, CommitAnnotation[]>
  >({});
  const [orphans, setOrphans] = useState<CommitAnnotation[]>([]);
  const [openHash, setOpenHash] = useState<string | null>(null);
  const [annotationBusy, setAnnotationBusy] = useState(false);
  const [stream, setStream] = useState<TimelineStream | null>(null);

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
  }, [projectId, llmVersion]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectTimeline(projectId)
      .then((data) => {
        if (!cancelled) {
          setTimeline(data);
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

  // 一次拉取全部批注，再按 commit hash 分组，避免逐条提交去请求
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listAnnotations(projectId),
      listAnnotations(projectId, { orphan: true }),
    ])
      .then(([all, orphanList]) => {
        if (cancelled) {
          return;
        }
        const grouped: Record<string, CommitAnnotation[]> = {};
        all.forEach((item) => {
          grouped[item.commit_hash] = [
            ...(grouped[item.commit_hash] ?? []),
            item,
          ];
        });
        setAnnotations(grouped);
        setOrphans(orphanList);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // 时间线事件流由后端把提交、Bug、笔记、批注合并好再返回。任何一处
  // 改动（例如新加一条批注）都要重新拉一次，因为批注本身也是时间线上
  // 的一个节点，只改本地数组的话那个节点不会出现。
  useEffect(() => {
    let cancelled = false;
    getProjectTimelineEvents(projectId)
      .then((data) => {
        if (!cancelled) {
          setStream(data);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, reloadKey]);

  async function handleTranslate() {
    setTranslating(true);
    setError("");
    setSuccess("");
    try {
      const result = await translateProjectCommits(projectId);
      if (result.translated_count > 0) {
        setSuccess(
          `已翻译 ${result.translated_count} 条提交信息。`,
        );
      } else if (result.remaining_count > 0) {
        setSuccess(
          `本次翻译 ${result.translated_count} 条，还有 ${result.remaining_count} 条可稍后重试。`,
        );
      } else {
        setSuccess("所有提交都已经翻译成中文了。");
      }
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTranslating(false);
    }
  }

  function toggleCommitAnnotations(hash: string) {
    setOpenHash((current) => (current === hash ? null : hash));
  }

  async function handleAddAnnotation(
    commitHash: string,
    kind: AnnotationKind,
    body: string,
  ) {
    const trimmed = body.trim();
    if (!trimmed) {
      setError("请先填写批注内容");
      return;
    }
    setAnnotationBusy(true);
    setError("");
    setSuccess("");
    try {
      const created = await addAnnotation(projectId, commitHash, {
        kind,
        body: trimmed,
      });
      setAnnotations((prev) => ({
        ...prev,
        [commitHash]: [...(prev[commitHash] ?? []), created],
      }));
      setSuccess("批注已添加");
      // 批注本身也是时间线上的一个节点，得让事件流重新合并一次。
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAnnotationBusy(false);
    }
  }

  async function handleDeleteAnnotation(annotation: CommitAnnotation) {
    setAnnotationBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await deleteAnnotation(annotation.id);
      if (!result.deleted) {
        setError("这条批注不存在，可能已被删除");
        return;
      }
      setAnnotations((prev) => ({
        ...prev,
        [annotation.commit_hash]: (prev[annotation.commit_hash] ?? []).filter(
          (item) => item.id !== annotation.id,
        ),
      }));
      setSuccess("批注已删除");
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAnnotationBusy(false);
    }
  }

  async function handleDeleteOrphan(annotation: CommitAnnotation) {
    setAnnotationBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await deleteAnnotation(annotation.id);
      if (!result.deleted) {
        setError("这条批注不存在，可能已被删除");
        return;
      }
      setOrphans((prev) => prev.filter((item) => item.id !== annotation.id));
      setSuccess("孤儿批注已删除");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAnnotationBusy(false);
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

  if (!timeline) {
    return (
      <main className="container">
        <button className="back-link" onClick={onBack}>
          ← 返回项目
        </button>
        <p className="message error">{error || "时间线数据加载失败"}</p>
      </main>
    );
  }

  const milestoneCount = timeline.themes.filter(
    (theme) => theme.is_milestone_candidate,
  ).length;
  const translatedCount = timeline.commits.filter(
    (item) => item.translated_subject !== null,
  ).length;
  const annotationCount = Object.values(annotations).reduce(
    (sum, items) => sum + items.length,
    0,
  );

  function commitsForTheme(theme: TimelineTheme): TimelineCommit[] {
    const hashes = new Set(theme.commit_hashes);
    return timeline!.commits
      .filter((item) => hashes.has(item.hash))
      .reverse();
  }

  function renderCommitRow(commit: TimelineCommit, isNoise: boolean) {
    const translated = commit.translated_subject?.trim();
    const commitAnnotations = annotations[commit.hash] ?? [];
    const isOpen = openHash === commit.hash;
    return (
      <div
        key={commit.hash}
        className={`commit-row${isNoise ? " commit-noise" : ""}`}
      >
        <div className="commit-meta">
          <span className="mono commit-hash">{commit.short_hash}</span>
          <span>{formatDateTime(commit.committed_at)}</span>
          {isNoise && (
            <span className="badge badge-noise">
              噪音 · {noiseLabel(commit.noise_type)}
            </span>
          )}
          <span className="commit-stats">
            <span className="commit-files">{commit.files_changed} 个文件</span>
            <span className="commit-add">+{commit.insertions}</span>
            <span className="commit-del">-{commit.deletions}</span>
          </span>
        </div>
        {translated ? (
          <>
            <div className="commit-subject commit-subject-zh">
              {translated}
            </div>
            <div className="commit-original">
              原文：{commit.message_subject}
            </div>
          </>
        ) : (
          <div className="commit-subject">{commit.message_subject}</div>
        )}
        <div className="commit-annotations">
          <button
            className="annotation-toggle"
            onClick={() => toggleCommitAnnotations(commit.hash)}
          >
            {isOpen
              ? "收起批注"
              : commitAnnotations.length > 0
                ? `批注 ${commitAnnotations.length}`
                : "添加批注"}
          </button>
          {isOpen && (
            <AnnotationPanel
              commitHash={commit.hash}
              annotations={commitAnnotations}
              busy={annotationBusy}
              onAdd={handleAddAnnotation}
              onDelete={handleDeleteAnnotation}
            />
          )}
        </div>
      </div>
    );
  }

  const themes = [...timeline.themes].reverse();

  return (
    <main className="container">
      <div className="page-head">
        <button className="back-link" onClick={onBack}>
          ← 返回项目
        </button>
        <h1>{projectName} · 开发时间线</h1>
        <p className="page-sub mono">{projectPath}</p>
      </div>

      {error && <p className="message error">{error}</p>}
      {success && <p className="message success">{success}</p>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">
            <Icon name="commit" className="stat-icon" />
            提交总数
          </div>
          <div className="stat-value">{timeline.commits.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">
            <Icon name="note" className="stat-icon" />
            已翻译为中文
          </div>
          <div className="stat-value accent">{translatedCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">
            <Icon name="tag" className="stat-icon" />
            开发主题
          </div>
          <div className="stat-value">{timeline.themes.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">
            <Icon name="gap" className="stat-icon" />
            静默期
          </div>
          <div className="stat-value warning">
            {timeline.silence_periods.length}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">
            <Icon name="annotation" className="stat-icon" />
            批注
          </div>
          <div className="stat-value">{annotationCount}</div>
        </div>
      </div>

      {stream ? (
        <TimelineRail
          events={stream.events}
          truncatedCount={stream.truncated_count}
          orphanAnnotationCount={stream.orphan_annotation_count}
          annotations={annotations}
          annotationBusy={annotationBusy}
          onAddAnnotation={handleAddAnnotation}
          onDeleteAnnotation={handleDeleteAnnotation}
        />
      ) : (
        <section className="panel">
          <div className="panel-head">
            <h2>开发时间线</h2>
            <span className="panel-hint">正在合并事件流…</span>
          </div>
        </section>
      )}

      {timeline.commits.length === 0 ? (
        <div className="empty">
          <strong>还没有可展示的提交</strong>
          先回到项目页执行“扫描仓库”，时间线会自动从 Git 历史中读取。
        </div>
      ) : (
        <>
          <section className="panel">
            <div className="panel-head">
              <h2>中文阅读模式</h2>
              <span className="panel-hint">
                原始英文信息始终保留，翻译结果只用于阅读
              </span>
            </div>
            <div className="actions">
              <button
                disabled={
                  translating ||
                  llmReady === false ||
                  translatedCount === timeline.commits.length
                }
                onClick={handleTranslate}
              >
                {translating
                  ? "翻译中…"
                  : llmReady === null
                    ? "检测 AI 配置…"
                    : llmReady
                      ? `翻译剩余提交（${timeline.commits.length - translatedCount}）`
                      : "AI 未配置"}
              </button>
            </div>
            {llmReady === false && (
              <p className="panel-hint" style={{ marginTop: 12 }}>
                接入大模型后即可一键把提交标题翻成中文：
                <button
                  type="button"
                  className="link-button"
                  onClick={onOpenSettings}
                >
                  去填写 API Key
                </button>
              </p>
            )}
          </section>

          <section className="section">
            <div className="panel-head">
              <h2>主题分组</h2>
              <span className="panel-hint">
                按提交信息自动聚类 · 共 {themes.length} 个主题
                {milestoneCount > 0
                  ? ` · ${milestoneCount} 个里程碑候选`
                  : ""}
              </span>
            </div>

            {themes.length === 0 && (
              <div className="empty">
                <strong>暂未形成开发主题</strong>
                当前提交可能都是噪音提交，重新扫描后仍会保留在提交流水中。
              </div>
            )}

            {themes.map((theme) => (
              <article key={theme.id} className="theme-card">
                <header className="theme-head">
                  <span className="theme-kind">
                    {kindLabel(theme.kind)}
                  </span>
                  <div className="theme-main">
                    <div className="theme-title">
                      开发主题 {themeNumber(theme)}
                    </div>
                    <div className="theme-meta">
                      {theme.commit_count} 个提交 ·{" "}
                      {formatRange(theme.started_at, theme.ended_at)}
                      {theme.is_milestone_candidate && (
                        <span className="badge badge-milestone">
                          里程碑候选
                        </span>
                      )}
                    </div>
                  </div>
                </header>
                <div className="theme-commits">
                  {commitsForTheme(theme).map((commit) =>
                    renderCommitRow(commit, false),
                  )}
                </div>
              </article>
            ))}
          </section>

          {orphans.length > 0 && (
            <section className="section">
              <div className="panel-head">
                <h2>孤儿批注</h2>
                <span className="panel-hint">
                  {orphans.length} 条 · 原 commit 已不在 Git 历史中
                </span>
              </div>
              <p className="panel-hint orphan-hint">
                通常是 rebase 或 force push 改写了历史。批注不会自动丢失，
                确认无用后可删除。
              </p>
              {orphans.map((item) => (
                <div key={item.id} className="orphan-card">
                  <div className="orphan-main">
                    <span
                      className={
                        item.kind === "decision"
                          ? "badge badge-confirmed"
                          : "badge badge-edited"
                      }
                    >
                      {item.kind === "decision" ? "决策" : "备注"}
                    </span>
                    <span className="annotation-body">{item.body}</span>
                  </div>
                  <div className="orphan-meta mono">
                    {item.commit_hash.slice(0, 7)} ·{" "}
                    {formatDateTime(item.created_at)}
                  </div>
                  <button
                    className="secondary danger tiny"
                    disabled={annotationBusy}
                    onClick={() => handleDeleteOrphan(item)}
                  >
                    删除
                  </button>
                </div>
              ))}
            </section>
          )}

          {timeline.silence_periods.length > 0 && (
            <section className="section">
              <div className="panel-head">
                <h2>静默期</h2>
                <span className="panel-hint">连续超过 3 天没有有效提交</span>
              </div>
              {timeline.silence_periods.map((period, index) => (
                <div key={index} className="silence-card">
                  <div className="silence-main">
                    <strong>{period.days} 天静默</strong>
                    <span>
                      {formatRange(period.started_at, period.ended_at)}
                    </span>
                  </div>
                  <p>
                    复盘时值得回忆：这段时间是在调研、等反馈，还是项目暂停了？
                  </p>
                </div>
              ))}
            </section>
          )}
        </>
      )}
    </main>
  );
}
