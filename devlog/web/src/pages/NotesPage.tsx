import { useEffect, useState } from "react";
import { listDailyNotes, saveDailyNote } from "../api";
import type { DailyNote } from "../types";
import { formatDate } from "../utils";

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
  const [loadingDay, setLoadingDay] = useState(true);
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
