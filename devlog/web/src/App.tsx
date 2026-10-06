import { useState } from "react";
import { Icon } from "./components/Icons";
import { SettingsDialog } from "./components/SettingsDialog";
import { useTheme, type ThemeName } from "./hooks/useTheme";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ReviewPage } from "./pages/ReviewPage";
import { TimelinePage } from "./pages/TimelinePage";
import { NotesPage } from "./pages/NotesPage";
import { BugsPage } from "./pages/BugsPage";

type View =
  | { name: "projects" }
  | {
      name: "project";
      projectId: number;
      projectName: string;
      projectPath: string;
    }
  | {
      name: "review";
      draftId: number;
      projectId: number;
      projectName: string;
      projectPath: string;
    }
  | {
      name: "timeline";
      projectId: number;
      projectName: string;
      projectPath: string;
    }
  | {
      name: "notes";
      projectId: number;
      projectName: string;
      projectPath: string;
    }
  | {
      name: "bugs";
      projectId: number;
      projectName: string;
      projectPath: string;
      // 从当天小结点进来时带上要定位的那条 Bug。
      focusBugId?: number | null;
    };

function TopBar({
  theme,
  onToggleTheme,
  onOpenSettings,
}: {
  theme: ThemeName;
  onToggleTheme: () => void;
  onOpenSettings: () => void;
}) {
  const nextTheme = theme === "dark" ? "浅色" : "深色";
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <span className="brand-mark">D</span>
          <span>
            <div className="brand-title">DevLog</div>
            <div className="brand-sub">开发复盘工作台</div>
          </span>
        </div>
        <div className="topbar-actions">
          <span className="topbar-chip">
            <span className="dot" />
            <span>本地模式 · Git 驱动</span>
          </span>
          <button
            type="button"
            className="icon-button"
            onClick={onToggleTheme}
            title={`切换到${nextTheme}主题`}
            aria-label={`切换到${nextTheme}主题`}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
          <button
            type="button"
            className="icon-button"
            onClick={onOpenSettings}
            title="大模型设置"
            aria-label="大模型设置"
          >
            <Icon name="settings" />
          </button>
        </div>
      </div>
    </header>
  );
}

export default function App() {
  const [view, setView] = useState<View>({ name: "projects" });
  const { theme, toggleTheme } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 在设置里存完密钥后 +1，页面据此重新读一次"AI 配好了没"。
  const [llmVersion, setLLMVersion] = useState(0);

  let page;
  if (view.name === "projects") {
    page = (
      <ProjectsPage
        onOpenProject={(projectId, projectName, projectPath) =>
          setView({
            name: "project",
            projectId,
            projectName,
            projectPath,
          })
        }
      />
    );
  } else if (view.name === "project") {
    page = (
      <ProjectPage
        projectId={view.projectId}
        projectName={view.projectName}
        projectPath={view.projectPath}
        llmVersion={llmVersion}
        onOpenSettings={() => setSettingsOpen(true)}
        onBack={() => setView({ name: "projects" })}
        onOpenTimeline={() =>
          setView({
            name: "timeline",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
        onOpenReview={(draftId) =>
          setView({
            name: "review",
            draftId,
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
        onOpenNotes={() =>
          setView({
            name: "notes",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
        onOpenBugs={() =>
          setView({
            name: "bugs",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
      />
    );
  } else if (view.name === "timeline") {
    page = (
      <TimelinePage
        projectId={view.projectId}
        projectName={view.projectName}
        projectPath={view.projectPath}
        llmVersion={llmVersion}
        onOpenSettings={() => setSettingsOpen(true)}
        onBack={() =>
          setView({
            name: "project",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
      />
    );
  } else if (view.name === "notes") {
    page = (
      <NotesPage
        projectId={view.projectId}
        projectName={view.projectName}
        projectPath={view.projectPath}
        onOpenBug={(bugId) =>
          setView({
            name: "bugs",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
            focusBugId: bugId,
          })
        }
        onBack={() =>
          setView({
            name: "project",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
      />
    );
  } else if (view.name === "bugs") {
    page = (
      <BugsPage
        projectId={view.projectId}
        projectName={view.projectName}
        projectPath={view.projectPath}
        focusBugId={view.focusBugId ?? null}
        onBack={() =>
          setView({
            name: "project",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
      />
    );
  } else {
    page = (
      <ReviewPage
        draftId={view.draftId}
        onBack={() =>
          setView({
            name: "project",
            projectId: view.projectId,
            projectName: view.projectName,
            projectPath: view.projectPath,
          })
        }
      />
    );
  }

  return (
    <div className="app-shell">
      <TopBar
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      {page}
      {settingsOpen && (
        <SettingsDialog
          onClose={() => setSettingsOpen(false)}
          onSaved={() => setLLMVersion((value) => value + 1)}
        />
      )}
    </div>
  );
}
