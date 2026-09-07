import { useState } from "react";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ReviewPage } from "./pages/ReviewPage";

type View =
  | { name: "projects" }
  | { name: "project"; projectId: number; projectName: string }
  | { name: "review"; draftId: number; projectId: number; projectName: string };

export default function App() {
  const [view, setView] = useState<View>({ name: "projects" });

  if (view.name === "projects") {
    return (
      <ProjectsPage
        onOpenProject={(projectId, projectName) =>
          setView({ name: "project", projectId, projectName })
        }
      />
    );
  }

  if (view.name === "project") {
    return (
      <ProjectPage
        projectId={view.projectId}
        projectName={view.projectName}
        onBack={() => setView({ name: "projects" })}
        onOpenReview={(draftId) =>
          setView({
            name: "review",
            draftId,
            projectId: view.projectId,
            projectName: view.projectName,
          })
        }
      />
    );
  }

  return (
    <ReviewPage
      draftId={view.draftId}
      onBack={() =>
        setView({
          name: "project",
          projectId: view.projectId,
          projectName: view.projectName,
        })
      }
    />
  );
}
