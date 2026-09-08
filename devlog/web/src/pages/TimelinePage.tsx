import { useEffect, useState } from "react";
import { getProjectTimeline } from "../api";
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

export function TimelinePage({
  projectId,
  projectName,
  projectPath,
  onBack,
}: TimelinePageProps) {
  const [timeline, setTimeline] = useState<ProjectTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showNoise, setShowNoise] = useState(false);

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
  }, [projectId]);

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
            <span className="commit-files">{commit.files_changed} files</span>
            <span className="commit-add">+{commit.insertions}</span>
            <span className="commit-del">-{commit.deletions}</span>
          </span>
        </div>
        <div className="commit-subject">{commit.message_subject}</div>
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

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">提交总数</div>
          <div className="stat-value">{timeline.commits.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">开发主题</div>
          <div className="stat-value accent">{timeline.themes.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">里程碑候选</div>
          <div className="stat-value success">{milestoneCount}</div>
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
          <section className="section">
            <div className="panel-head">
              <h2>主题分组</h2>
              <span className="panel-hint">
                按提交信息自动聚类 · 共 {themes.length} 个主题
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
                    <div className="theme-title">{theme.title}</div>
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
