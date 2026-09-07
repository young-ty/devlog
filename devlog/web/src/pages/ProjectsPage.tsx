import { useEffect, useState, type FormEvent } from "react";
import { createProject, listProjects } from "../api";
import type { Project } from "../types";

interface ProjectsPageProps {
  onOpenProject: (projectId: number, projectName: string) => void;
}

export function ProjectsPage({ onOpenProject }: ProjectsPageProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
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
    try {
      await createProject(path, name || undefined);
      setPath("");
      setName("");
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <h1>DevLog 项目</h1>
      {error && <p className="error">{error}</p>}

      <section className="card">
        <h2>注册 Git 仓库</h2>
        <form onSubmit={handleSubmit}>
          <input
            required
            placeholder="仓库绝对路径，如 D:\work\demo"
            value={path}
            onChange={(event) => setPath(event.target.value)}
          />
          <input
            placeholder="项目名（可选，默认用文件夹名）"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button type="submit" disabled={busy || !path}>
            {busy ? "注册中…" : "注册"}
          </button>
        </form>
      </section>

      <section>
        <h2>已注册项目</h2>
        {loading && <p>加载中…</p>}
        {!loading && projects.length === 0 && <p>还没有项目，先注册一个。</p>}
        {projects.map((project) => (
          <button
            key={project.project_id}
            className="project-row"
            onClick={() => onOpenProject(project.project_id, project.name)}
          >
            <strong>{project.name}</strong>
            <span className="muted">{project.path}</span>
          </button>
        ))}
      </section>
    </main>
  );
}
