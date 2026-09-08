import { useEffect, useState } from "react";
import {
  getLLMConfig,
  getProjectTimeline,
  translateProjectCommits,
} from "../api";
import type {
  ProjectTimeline,
  TimelineCommit,
  TimelineTheme,
} from "../types";
import { formatDateTime, formatRange } from "../utils";

interface TimelinePageProps {
  projectId: number;
  projectName: string;
  projectPath: string;
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
  onBack,
}: TimelinePageProps) {
  const [timeline, setTimeline] = useState<ProjectTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [translating, setTranslating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [showNoise, setShowNoise] = useState(false);
  const [llmReady, setLLMReady] = useState<boolean | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

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

  const noiseCount = timeline.commits.filter(
    (item) => item.noise_type !== "none",
  ).length;
  const milestoneCount = timeline.themes.filter(
    (theme) => theme.is_milestone_candidate,
  ).length;
  const translatedCount = timeline.commits.filter(
    (item) => item.translated_subject !== null,
  ).length;
  const visibleCommits = timeline.commits.filter(
    (item) => showNoise || item.noise_type === "none",
  );

  function commitsForTheme(theme: TimelineTheme): TimelineCommit[] {
    const hashes = new Set(theme.commit_hashes);
    return timeline!.commits
      .filter((item) => hashes.has(item.hash))
      .reverse();
  }

  function renderCommitRow(commit: TimelineCommit, isNoise: boolean) {
    const translated = commit.translated_subject?.trim();
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
      </div>
    );
  }

  const themes = [...timeline.themes].reverse();
  const commits = [...visibleCommits].reverse();

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
          <div className="stat-label">提交总数</div>
          <div className="stat-value">{timeline.commits.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">已翻译为中文</div>
          <div className="stat-value accent">{translatedCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">开发主题</div>
          <div className="stat-value">{timeline.themes.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">静默期</div>
          <div className="stat-value warning">
            {timeline.silence_periods.length}
          </div>
        </div>
      </div>

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
                配置 ~/.devlog/config.toml 中的 DeepSeek api_key
                后即可一键翻译全部提交。
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

          <section className="section">
            <div className="panel-head">
              <h2>提交流水</h2>
              <span className="panel-hint">
                {commits.length} 条{noiseCount > 0 && ` · ${noiseCount} 条噪音`}
              </span>
            </div>

            <label className="toggle">
              <input
                type="checkbox"
                checked={showNoise}
                onChange={(event) => setShowNoise(event.target.checked)}
              />
              显示噪音提交（merge / revert / wip / chore）
            </label>

            <div className="commit-list">
              {commits.map((commit) =>
                renderCommitRow(commit, commit.noise_type !== "none"),
              )}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
