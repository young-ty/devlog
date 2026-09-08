import type {
  ConfirmResult,
  ExportResult,
  GenerateResult,
  InitResult,
  Project,
  ProjectTimeline,
  ReviewDraft,
  ReviewSummary,
  ScanResult,
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
      // response is not JSON; keep the generic message
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
