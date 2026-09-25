import { useEffect, useState } from "react";
import {
  getDayDigest,
  listDailyNotes,
  saveDailyNote,
  scanProject,
} from "../api";
import { Icon } from "../components/Icons";
import type { DailyNote, DayDigest } from "../types";
import {
  BUG_STATUS_LABELS,
  formatClockTime,
  formatDate,
  formatSpan,
} from "../utils";

interface NotesPageProps {
  projectId: number;
  projectName: string;
  projectPath: string;
  onBack: () => void;
}

function todayISO(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function NotesPage({
  projectId,
  projectName,
  projectPath,
  onBack,
}: NotesPageProps) {
  const [selectedDate, setSelectedDate] = useState(todayISO);
  const [summary, setSummary] = useState("");
  const [issues, setIssues] = useState("");
  const [plan, setPlan] = useState("");
  const [history, setHistory] = useState<DailyNote[]>([]);
  const [digest, setDigest] = useState<DayDigest | null>(null);
  const [loadingDay, setLoadingDay] = useState(true);
  const [loadingDigest, setLoadingDigest] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [historyKey, setHistoryKey] = useState(0);

  // 切换日期时，回填当天已保存的内容
  useEffect(() => {
    let cancelled = false;
    setLoadingDay(true);
    setError("");
    listDailyNotes(projectId, selectedDate)
      .then((items) => {
        if (cancelled) {
          return;
        }
        const note = items[0];
        setSummary(note?.summary ?? "");
        setIssues(note?.issues ?? "");
        setPlan(note?.plan ?? "");
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingDay(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedDate]);

  // 当天小结：和笔记分开加载。笔记没读出来不该挡着"今天干了什么"，
  // 反过来也一样，两个请求互不拖累。
  useEffect(() => {
    let cancelled = false;
    setLoadingDigest(true);
    getDayDigest(projectId, selectedDate)
      .then((item) => {
        if (!cancelled) {
          setDigest(item);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingDigest(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedDate]);

  // 加载历史笔记（新的在前）；保存成功后通过 historyKey 刷新
  useEffect(() => {
    let cancelled = false;
    setLoadingHistory(true);
    listDailyNotes(projectId)
      .then((items) => {
        if (!cancelled) {
          setHistory(items);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingHistory(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, historyKey]);

  async function handleSave() {
    if (!selectedDate) {
      return;
    }
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await saveDailyNote(projectId, {
        note_date: selectedDate,
        summary,
        issues,
        plan,
      });
      setSuccess(`已保存 ${formatDate(selectedDate)} 的复盘`);
      setHistoryKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function openHistoryNote(note: DailyNote) {
    setSuccess("");
    setSelectedDate(note.note_date);
  }

  function handleDraftFromDigest() {
    if (!digest || !digest.draft_text) {
      return;
    }
    if (
      summary.trim() &&
      !window.confirm(
        "「今天做了什么」里已经有内容了，用提交记录起草会覆盖它。继续吗？",
      )
    ) {
      return;
    }
    setSummary(digest.draft_text);
    setSuccess("已按当天的提交列出草稿，接着改成你自己的话就行。");
  }

  async function handleScan() {
    setScanning(true);
    setError("");
    setSuccess("");
    try {
      const result = await scanProject(projectId);
      const refreshed = await getDayDigest(projectId, selectedDate);
      setDigest(refreshed);
      setHistoryKey((key) => key + 1);
      setSuccess(
        result.inserted_events > 0
          ? `扫描完成，新增 ${result.inserted_events} 条提交。`
          : "扫描完成，没有新的提交。",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setScanning(false);
    }
  }

  const commitSpan =
    digest?.first_commit_at && digest?.last_commit_at
      ? `${formatClockTime(digest.first_commit_at)}–${formatClockTime(
          digest.last_commit_at,
        )}`
      : "";

  return (
    <main className="container">
      <div className="page-head">
        <button className="back-link" onClick={onBack}>
          ← 返回项目
        </button>
        <h1>每日复盘</h1>
        <p className="page-sub">
          {projectName}
          <span className="mono"> · {projectPath}</span>
        </p>
      </div>

      {error && <p className="message error">{error}</p>}
      {success && <p className="message success">{success}</p>}

      <section className="panel">
        <div className="panel-head">
          <h2>当天都发生了什么</h2>
          <span className="panel-hint">
            {loadingDigest ? "读取中…" : "全部来自 Git 提交与 Bug 捕获"}
          </span>
        </div>

        {loadingDigest && <div className="skeleton" />}

        {!loadingDigest && digest && !digest.has_cached_commits && (
          <div className="empty">
            <strong>这个仓库还没有扫描过提交</strong>
            先回项目页点「扫描」，这里才有当天的记录可看。
          </div>
        )}

        {!loadingDigest &&
          digest &&
          digest.has_cached_commits &&
          digest.is_empty && (
            <div className="empty">
              <strong>这一天没有提交，也没有捕获到 Bug</strong>
              没动手的日子不用硬写，留空就行。
            </div>
          )}

        {!loadingDigest &&
          digest &&
          digest.has_cached_commits &&
          !digest.is_empty && (
            <>
              {digest.commit_count > 0 && (
                <p className="digest-stats">
                  <span>{digest.commit_count} 次提交</span>
                  <span>{digest.file_count} 个文件</span>
                  <span className="mono">
                    +{digest.insertions} / -{digest.deletions}
                  </span>
                  {commitSpan && (
                    <span className="mono">
                      {commitSpan}
                      {digest.active_minutes !== null &&
                        ` · 跨度 ${formatSpan(digest.active_minutes)}`}
                    </span>
                  )}
                </p>
              )}
              <ul className="digest-list">
                {digest.commits.map((item) => (
                  <li key={item.short_hash} className="digest-row">
                    <Icon name="commit" className="digest-icon" />
                    <span className="digest-time mono">
                      {formatClockTime(item.committed_at)}
                    </span>
                    <span className="digest-subject">{item.subject}</span>
                    <span className="digest-hash mono">{item.short_hash}</span>
                  </li>
                ))}
                {digest.bugs.map((bug) => (
                  <li key={`bug-${bug.id}`} className="digest-row">
                    <Icon name="bug" className="digest-icon" />
                    <span className="digest-time mono">
                      {bug.captured_at ? formatClockTime(bug.captured_at) : "—"}
                    </span>
                    <span className="digest-subject">{bug.title}</span>
                    <span className={`badge badge-${bug.status}`}>
                      {BUG_STATUS_LABELS[bug.status]}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={!digest.draft_text}
                  onClick={handleDraftFromDigest}
                >
                  用提交记录起草
                </button>
                {/* 小结读的是扫描缓存，刚提交完就来看会缺最新几条，
                    所以把"重新扫描"直接放在这里，不用回去找项目页。 */}
                <button
                  type="button"
                  className="secondary"
                  disabled={scanning}
                  onClick={() => void handleScan()}
                >
                  {scanning ? "扫描中…" : "扫描最新提交"}
                </button>
                <span className="form-hint">
                  只把当天的提交排成列表，写什么由你决定。
                </span>
              </div>
            </>
          )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>写一笔</h2>
          <span className="panel-hint">
            {loadingDay
              ? "正在读取当天内容…"
              : "花 2 分钟记下今天，完工复盘时就不用拼命回忆"}
          </span>
        </div>
        <div className="notes-form">
          <label className="field-row">
            <span className="field-label">日期</span>
            <input
              className="date-input"
              type="date"
              value={selectedDate}
              max={todayISO()}
              onChange={(event) => {
                setSuccess("");
                setSelectedDate(event.target.value);
              }}
              disabled={loadingDay}
            />
          </label>
          <textarea
            rows={3}
            placeholder="今天做了什么？（例如：完成 Git 扫描器，处理了中文乱码）"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            disabled={loadingDay}
          />
          <textarea
            rows={2}
            placeholder="遇到什么问题？（可留空）"
            value={issues}
            onChange={(event) => setIssues(event.target.value)}
            disabled={loadingDay}
          />
          <textarea
            rows={2}
            placeholder="明天计划做什么？（可留空）"
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            disabled={loadingDay}
          />
          <div className="actions">
            <button
              disabled={saving || loadingDay || !selectedDate}
              onClick={handleSave}
            >
              {saving ? "保存中…" : "保存笔记"}
            </button>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="panel-head">
          <h2>历史笔记</h2>
          <span className="panel-hint">
            {loadingHistory
              ? "读取中…"
              : `${history.length} 天 · 点击可回看`}
          </span>
        </div>

        {loadingHistory && (
          <>
            <div className="skeleton" />
            <div className="skeleton" />
          </>
        )}

        {!loadingHistory && history.length === 0 && (
          <div className="empty">
            <strong>还没有写过每日复盘</strong>
            从今天开始，每天花 2 分钟记录一下。
          </div>
        )}

        {history.map((note) => (
          <button
            key={note.id}
            className="item-card"
            onClick={() => openHistoryNote(note)}
          >
            <div className="item-top">
              <div>
                <div className="item-title">{formatDate(note.note_date)}</div>
                <div className="item-path">
                  {note.summary.split("\n")[0] || "（当天没有内容）"}
                </div>
              </div>
              <span className="arrow">→</span>
            </div>
          </button>
        ))}
      </section>
    </main>
  );
}
