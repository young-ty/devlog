import { useEffect, useState, type FormEvent } from "react";
import { createProject, listProjects, pickDirectory } from "../api";
import type { Project } from "../types";
import { folderName, formatDateTime } from "../utils";

interface ProjectsPageProps {
  onOpenProject: (
    projectId: number,
    projectName: string,
    projectPath: string,
  ) => void;
}

export function ProjectsPage({ onOpenProject }: ProjectsPageProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listProjects()
      .then((items) => {
        if (!cancelled) {
          setProjects(items);
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
  }, [reloadKey]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await createProject(path, name || undefined);
      setSuccess(`已注册项目：${result.project_name}`);
      setPath("");
      setName("");
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleBrowse() {
    setPicking(true);
    setError("");
    setSuccess("");
    try {
      const result = await pickDirectory();
      if (result.cancelled || !result.path) {
        // 用户点了取消：什么都不做，不要弹错误吓人。
        return;
      }
      setPath(result.path);
      if (!name.trim()) {
        setName(folderName(result.path));
      }
      if (!result.is_git_repo) {
        setError(
          `已选择 ${result.path}，但这个文件夹不是 Git 仓库（找不到 .git）。请选择仓库根目录，或先在该目录执行 git init。`,
        );
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPicking(false);
    }
  }

  const scannedCount = projects.filter(
    (project) => project.last_scanned_commit !== null,
  ).length;

  return (
    <main className="container">
      <div className="page-head">
        <h1>项目</h1>
        <p className="page-sub">
          选择要复盘的本机 Git 仓库。DevLog 只读 Git 历史，不会改动你的仓库。
        </p>
      </div>

      {error && <p className="message error">{error}</p>}
      {success && <p className="message success">{success}</p>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">已注册项目</div>
          <div className="stat-value">{projects.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">已扫描仓库</div>
          <div className="stat-value accent">{scannedCount}</div>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>注册 Git 仓库</h2>
          <span className="panel-hint">路径只在本地访问</span>
        </div>
        <form className="form-grid" onSubmit={handleSubmit}>
          <div className="path-row">
            <input
              required
              placeholder="仓库绝对路径，例如 D:\work\demo"
              value={path}
              onChange={(event) => setPath(event.target.value)}
            />
            <button
              type="button"
              className="secondary"
              onClick={handleBrowse}
              disabled={picking || busy}
            >
              {picking ? "选择中…" : "浏览…"}
            </button>
          </div>
          {picking && (
            <p className="form-hint">
              已打开系统文件夹选择框，请到弹出的窗口里选一个仓库目录。
            </p>
          )}
          <input
            placeholder="项目名（可选，默认用文件夹名）"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button type="submit" disabled={busy || !path.trim()}>
            {busy ? "注册中…" : "注册项目"}
          </button>
        </form>
      </section>

      <section className="section">
        <div className="panel-head">
          <h2>已注册项目</h2>
          <span className="panel-hint">
            {loading ? "读取中…" : `${projects.length} 个`}
          </span>
        </div>

        {loading && (
          <>
            <div className="skeleton" />
            <div className="skeleton" />
          </>
        )}

        {!loading && projects.length === 0 && (
          <div className="empty">
            <strong>还没有注册任何项目</strong>
            把要复盘的项目路径填到上方，点击“注册项目”。
          </div>
        )}

        {projects.map((project) => (
          <button
            key={project.project_id}
            className="item-card"
            onClick={() =>
              onOpenProject(
                project.project_id,
                project.name,
                project.path,
              )
            }
          >
            <div className="item-top">
              <div>
                <div className="item-title">{project.name}</div>
                <div className="item-path mono">{project.path}</div>
              </div>
              <span className="arrow">→</span>
            </div>
            <div className="item-meta">
              <span>
                {project.last_scanned_commit
                  ? `上次扫描 ${project.last_scanned_commit.slice(0, 7)}`
                  : "尚未扫描"}
              </span>
              <span>注册于 {formatDateTime(project.created_at)}</span>
            </div>
          </button>
        ))}
      </section>
    </main>
  );
}
