import { useState } from "react";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ReviewPage } from "./pages/ReviewPage";
import { TimelinePage } from "./pages/TimelinePage";

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
    };

function TopBar() {
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
        <span className="topbar-chip">
          <span className="dot" />
          <span>本地模式 · Git 驱动</span>
        </span>
      </div>
    </header>
  );
}

export default function App() {
  const [view, setView] = useState<View>({ name: "projects" });

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
      />
    );
  } else if (view.name === "timeline") {
    page = (
      <TimelinePage
        projectId={view.projectId}
        projectName={view.projectName}
        projectPath={view.projectPath}
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
      <TopBar />
      {page}
    </div>
  );
}
