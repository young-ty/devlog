import { useEffect, useRef, useState } from "react";
import {
  captureBug,
  deleteBug,
  listBugs,
  suggestBugTitle,
  updateBug,
} from "../api";
import type { BugCaptureInput, BugRecord, BugStatus } from "../types";
import { BUG_STATUS_LABELS, formatDateTime } from "../utils";

interface BugsPageProps {
  projectId: number;
  projectName: string;
  projectPath: string;
  onBack: () => void;
  /** 从当天小结跳进来时要定位的那条 Bug；普通进入时为空。 */
  focusBugId?: number | null;
}

interface BugDraft {
  title: string;
  root_cause: string;
  solution: string;
}

type BugFilter = "all" | BugStatus;

const STATUS_ORDER: BugStatus[] = ["open", "root_cause_found", "resolved"];

export function BugsPage({
  projectId,
  projectName,
  projectPath,
  onBack,
  focusBugId = null,
}: BugsPageProps) {
  const [bugs, setBugs] = useState<BugRecord[]>([]);
  const [drafts, setDrafts] = useState<Record<number, BugDraft>>({});
  const [filter, setFilter] = useState<BugFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [errorText, setErrorText] = useState("");
  const [title, setTitle] = useState("");
  const [aiSuggested, setAiSuggested] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [busyBugId, setBusyBugId] = useState<number | null>(null);
  // 只在刚跳进来时定位一次：之后用户自己改状态、重新排序都不该再被拽走。
  const focusedOnce = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listBugs(projectId)
      .then((items) => {
        if (cancelled) {
          return;
        }
        setBugs(items);
        setDrafts(
          Object.fromEntries(
            items.map((bug) => [
              bug.id,
              {
                title: bug.title,
                root_cause: bug.root_cause,
                solution: bug.solution,
              },
            ]),
          ),
        );
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

  // 从当天小结点进来：先把筛选切回"全部"（否则这条可能被筛掉），
  // 再滚到它跟前。只做一次，之后用户自己操作不该被反复拽走。
  useEffect(() => {
    if (focusBugId === null || loading || focusedOnce.current) {
      return;
    }
    if (!bugs.some((bug) => bug.id === focusBugId)) {
      return;
    }
    focusedOnce.current = true;
    setFilter("all");
    document
      .getElementById(`bug-${focusBugId}`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusBugId, loading, bugs]);

  function applyUpdatedBug(updated: BugRecord) {
    setBugs((prev) =>
      prev.map((bug) => (bug.id === updated.id ? updated : bug)),
    );
    setDrafts((prev) => ({
      ...prev,
      [updated.id]: {
        title: updated.title,
        root_cause: updated.root_cause,
        solution: updated.solution,
      },
    }));
  }

  async function handleSuggestTitle() {
    if (!errorText.trim()) {
      setError("请先粘贴报错内容，再让 AI 建议标题");
      return;
    }
    setAiBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await suggestBugTitle({
        error_text: errorText,
      });
      setTitle(result.title);
      setAiSuggested(true);
      setSuccess("AI 标题建议已填入，可手动修改");
    } catch (err) {
      setError(`AI 建议失败：${(err as Error).message}`);
    } finally {
      setAiBusy(false);
    }
  }

  async function handleCapture() {
    if (!errorText.trim()) {
      setError("请先粘贴报错内容");
      return;
    }
    setCapturing(true);
    setError("");
    setSuccess("");
    try {
      const trimmedTitle = title.trim();
      const payload: BugCaptureInput = {
        error_text: errorText,
      };
      if (trimmedTitle) {
        payload.title = trimmedTitle;
        payload.title_source = aiSuggested ? "ai" : "manual";
      }
      const bug = await captureBug(projectId, payload);
      setBugs((prev) => [bug, ...prev]);
      setDrafts((prev) => ({
        ...prev,
        [bug.id]: {
          title: bug.title,
          root_cause: bug.root_cause,
          solution: bug.solution,
        },
      }));
      setErrorText("");
      setTitle("");
      setAiSuggested(false);
      setSuccess(`已捕获 Bug #${bug.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCapturing(false);
    }
  }

  async function handleStatus(bugId: number, status: BugStatus) {
    setBusyBugId(bugId);
    setError("");
    setSuccess("");
    try {
      const updated = await updateBug(bugId, { status });
      applyUpdatedBug(updated);
      setSuccess(`状态已更新：${BUG_STATUS_LABELS[status]}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyBugId(null);
    }
  }

  async function handleSaveDetails(bugId: number) {
    const draft = drafts[bugId];
    if (!draft) {
      return;
    }
    setBusyBugId(bugId);
    setError("");
    setSuccess("");
    try {
      const updated = await updateBug(bugId, {
        title: draft.title,
        root_cause: draft.root_cause,
        solution: draft.solution,
      });
      applyUpdatedBug(updated);
      setSuccess("修改已保存");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyBugId(null);
    }
  }

  async function handleDelete(bugId: number) {
    if (!window.confirm("确定删除这条 Bug 记录吗？删除后无法恢复。")) {
      return;
    }
    setBusyBugId(bugId);
    setError("");
    setSuccess("");
    try {
      const result = await deleteBug(bugId);
      if (result.deleted) {
        setBugs((prev) => prev.filter((bug) => bug.id !== bugId));
        setSuccess("Bug 记录已删除");
      } else {
        setError("这条 Bug 记录不存在，可能已被删除");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyBugId(null);
    }
  }

  const visibleBugs =
    filter === "all" ? bugs : bugs.filter((bug) => bug.status === filter);
  const openCount = bugs.filter((bug) => bug.status === "open").length;

  return (
    <main className="container">
      <div className="page-head">
        <button className="back-link" onClick={onBack}>
          ← 返回项目
        </button>
        <h1>Bug 清单</h1>
        <p className="page-sub">
          {projectName}
          <span className="mono"> · {projectPath}</span>
        </p>
      </div>

      {error && <p className="message error">{error}</p>}
      {success && <p className="message success">{success}</p>}

      <section className="panel">
        <div className="panel-head">
          <h2>捕获 Bug</h2>
          <span className="panel-hint">
            自动记录环境与 Git 现场，事后补充根因和解决方案
          </span>
        </div>
        <div className="notes-form">
          <textarea
            rows={5}
            placeholder="粘贴报错内容、Traceback、异常信息…"
            value={errorText}
            onChange={(event) => setErrorText(event.target.value)}
          />
          <input
            placeholder="标题（可留空，AI 可帮忙起）"
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              setAiSuggested(false);
            }}
          />
          <div className="actions">
            <button
              className="secondary"
              disabled={aiBusy || capturing}
              onClick={handleSuggestTitle}
            >
              {aiBusy ? "AI 思考中…" : "AI 建议标题"}
            </button>
            <button disabled={capturing} onClick={handleCapture}>
              {capturing ? "捕获中…" : "捕获 Bug"}
            </button>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="panel-head">
          <h2>全部记录</h2>
          <span className="panel-hint">
            {loading ? "读取中…" : `${bugs.length} 条 · ${openCount} 条未解决`}
          </span>
        </div>

        <div className="actions filter-row">
          {(["all", ...STATUS_ORDER] as BugFilter[]).map((item) => (
            <button
              key={item}
              className={filter === item ? "" : "secondary"}
              onClick={() => setFilter(item)}
            >
              {item === "all" ? "全部" : BUG_STATUS_LABELS[item]}
            </button>
          ))}
        </div>

        {loading && (
          <>
            <div className="skeleton" />
            <div className="skeleton" />
          </>
        )}

        {!loading && visibleBugs.length === 0 && (
          <div className="empty">
            <strong>{filter === "all" ? "还没有 Bug 记录" : "没有这个状态的 Bug"}</strong>
            遇到报错时，在上方粘贴并点击“捕获 Bug”。
          </div>
        )}

        {visibleBugs.map((bug) => {
          const draft = drafts[bug.id] ?? {
            title: bug.title,
            root_cause: bug.root_cause,
            solution: bug.solution,
          };
          return (
            <div
              key={bug.id}
              id={`bug-${bug.id}`}
              className={
                bug.id === focusBugId ? "bug-card bug-card-focus" : "bug-card"
              }
            >
              <div className="item-top">
                <div>
                  <div className="item-title">#{bug.id} {bug.title}</div>
                  <div className="item-meta">
                    <span>{formatDateTime(bug.captured_at)}</span>
                    <span>来源 {bug.title_source === "ai" ? "AI 建议" : "手动"}</span>
                  </div>
                </div>
                <span className={`badge badge-${bug.status}`}>
                  {BUG_STATUS_LABELS[bug.status]}
                </span>
              </div>

              <div className="bug-snapshot mono">
                <div>环境：{bug.environment || "未知"}</div>
                <div>Git HEAD：{bug.git_head || "未知"}</div>
                <div>工作区：{bug.git_status || "未知"}</div>
              </div>

              {bug.error_text && (
                <pre className="bug-error">{bug.error_text}</pre>
              )}

              <div className="notes-form compact">
                <input
                  placeholder="标题"
                  value={draft.title}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [bug.id]: { ...draft, title: event.target.value },
                    }))
                  }
                />
                <input
                  placeholder="根因（定位到哪一行/哪个模块/为什么）"
                  value={draft.root_cause}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [bug.id]: { ...draft, root_cause: event.target.value },
                    }))
                  }
                />
                <input
                  placeholder="解决方案"
                  value={draft.solution}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [bug.id]: { ...draft, solution: event.target.value },
                    }))
                  }
                />
              </div>

              <div className="actions bug-actions">
                <button
                  disabled={busyBugId === bug.id}
                  onClick={() => handleSaveDetails(bug.id)}
                >
                  保存修改
                </button>
                {STATUS_ORDER.map((status) => (
                  <button
                    key={status}
                    className={bug.status === status ? "" : "secondary"}
                    disabled={busyBugId === bug.id}
                    onClick={() => handleStatus(bug.id, status)}
                  >
                    {BUG_STATUS_LABELS[status]}
                  </button>
                ))}
                <button
                  className="secondary danger"
                  disabled={busyBugId === bug.id}
                  onClick={() => handleDelete(bug.id)}
                >
                  删除
                </button>
              </div>
            </div>
          );
        })}
      </section>
    </main>
  );
}
