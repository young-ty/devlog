import type {
  AnnotationCreateInput,
  AnnotationUpdateInput,
  BugCaptureInput,
  BugRecord,
  BugStatus,
  BugUpdateInput,
  CommitAnnotation,
  ConfirmResult,
  DailyNote,
  DailyNoteInput,
  DirectoryPickResult,
  ExportResult,
  GenerateResult,
  InitResult,
  LLMConfig,
  Project,
  ProjectTimeline,
  ReviewDraft,
  ReviewSummary,
  ScanResult,
  SuggestTitleInput,
  SuggestTitleResult,
  TranslationResult,
} from "./types";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // 响应不是 JSON；保留通用错误信息
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

function queryString(
  params: Record<string, string | boolean | undefined>,
): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function createProject(
  path: string,
  name?: string,
): Promise<InitResult> {
  return request<InitResult>(
    "/api/projects",
    jsonInit("POST", { path, name: name || undefined }),
  );
}

export function pickDirectory(): Promise<DirectoryPickResult> {
  return request<DirectoryPickResult>(
    "/api/system/pick-directory",
    jsonInit("POST", {}),
  );
}

export function scanProject(
  projectId: number,
  reset = false,
): Promise<ScanResult> {
  return request<ScanResult>(
    `/api/projects/${projectId}/scan`,
    jsonInit("POST", { reset }),
  );
}

export function getProjectTimeline(
  projectId: number,
): Promise<ProjectTimeline> {
  return request<ProjectTimeline>(
    `/api/projects/${projectId}/timeline`,
  );
}

export function getLLMConfig(): Promise<LLMConfig> {
  return request<LLMConfig>("/api/llm/config");
}

export function translateProjectCommits(
  projectId: number,
): Promise<TranslationResult> {
  return request<TranslationResult>(
    `/api/projects/${projectId}/translations`,
    jsonInit("POST", {}),
  );
}

export function listReviews(projectId: number): Promise<ReviewSummary[]> {
  return request<ReviewSummary[]>(`/api/projects/${projectId}/reviews`);
}

export function generateReview(
  projectId: number,
  offline = true,
): Promise<GenerateResult> {
  return request<GenerateResult>(
    `/api/projects/${projectId}/reviews/generate`,
    jsonInit("POST", { offline }),
  );
}

export function getReviewDraft(draftId: number): Promise<ReviewDraft> {
  return request<ReviewDraft>(`/api/reviews/${draftId}`);
}

export function confirmClaims(
  draftId: number,
  options: { claimIds?: number[]; all?: boolean; note?: string },
): Promise<ConfirmResult> {
  const body: Record<string, unknown> = {};
  if (options.claimIds) {
    body.claim_ids = options.claimIds;
  }
  if (options.all) {
    body.all = true;
  }
  if (options.note !== undefined && options.note !== "") {
    body.note = options.note;
  }
  return request<ConfirmResult>(
    `/api/reviews/${draftId}/confirm`,
    jsonInit("POST", body),
  );
}

export function exportReview(draftId: number): Promise<ExportResult> {
  return request<ExportResult>(
    `/api/reviews/${draftId}/export`,
    jsonInit("POST", {}),
  );
}

export function listDailyNotes(
  projectId: number,
  noteDate?: string,
): Promise<DailyNote[]> {
  return request<DailyNote[]>(
    `/api/projects/${projectId}/notes${queryString({
      note_date: noteDate,
    })}`,
  );
}

export function saveDailyNote(
  projectId: number,
  payload: DailyNoteInput,
): Promise<DailyNote> {
  return request<DailyNote>(
    `/api/projects/${projectId}/notes`,
    jsonInit("POST", payload),
  );
}

export function listBugs(
  projectId: number,
  status?: BugStatus,
): Promise<BugRecord[]> {
  return request<BugRecord[]>(
    `/api/projects/${projectId}/bugs${queryString({ status })}`,
  );
}

export function captureBug(
  projectId: number,
  payload: BugCaptureInput,
): Promise<BugRecord> {
  return request<BugRecord>(
    `/api/projects/${projectId}/bugs`,
    jsonInit("POST", payload),
  );
}

export function updateBug(
  bugId: number,
  payload: BugUpdateInput,
): Promise<BugRecord> {
  return request<BugRecord>(`/api/bugs/${bugId}`, jsonInit("PATCH", payload));
}

export function deleteBug(bugId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/api/bugs/${bugId}`,
    jsonInit("DELETE"),
  );
}

export function suggestBugTitle(
  payload: SuggestTitleInput,
): Promise<SuggestTitleResult> {
  return request<SuggestTitleResult>(
    "/api/bugs/suggest-title",
    jsonInit("POST", payload),
  );
}

export function listAnnotations(
  projectId: number,
  options: { commitHash?: string; orphan?: boolean } = {},
): Promise<CommitAnnotation[]> {
  return request<CommitAnnotation[]>(
    `/api/projects/${projectId}/annotations${queryString({
      commit_hash: options.commitHash,
      orphan: options.orphan,
    })}`,
  );
}

export function addAnnotation(
  projectId: number,
  commitHash: string,
  payload: AnnotationCreateInput,
): Promise<CommitAnnotation> {
  return request<CommitAnnotation>(
    `/api/projects/${projectId}/commits/${commitHash}/annotations`,
    jsonInit("POST", payload),
  );
}

export function updateAnnotation(
  annotationId: number,
  payload: AnnotationUpdateInput,
): Promise<CommitAnnotation> {
  return request<CommitAnnotation>(
    `/api/annotations/${annotationId}`,
    jsonInit("PATCH", payload),
  );
}

export function deleteAnnotation(
  annotationId: number,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/api/annotations/${annotationId}`,
    jsonInit("DELETE"),
  );
}
