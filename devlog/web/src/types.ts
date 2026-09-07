export type ClaimStatus = "fact" | "ai_pending" | "confirmed" | "edited";

export interface Project {
  project_id: number;
  name: string;
  path: string;
  created_at: string;
  last_scanned_commit: string | null;
}

export interface InitResult {
  project_id: number;
  project_name: string;
  project_path: string;
}

export interface ScanResult {
  project_id: number;
  project_name: string;
  project_path: string;
  total_events: number;
  inserted_events: number;
  reset: boolean;
}

export interface GenerateResult {
  draft_id: number;
  project_name: string;
  project_path: string;
  range_start: string;
  range_end: string;
  claim_count: number;
  ai_pending_count: number;
  question_count: number;
  offline: boolean;
}

export interface ReviewSummary {
  draft_id: number;
  project_id: number;
  project_name: string;
  project_path: string;
  range_start: string;
  range_end: string;
  created_at: string;
  total_claims: number;
  ai_pending_claims: number;
  confirmed_claims: number;
}

export interface ReviewClaim {
  id: number;
  section: string;
  text: string;
  sources: string[];
  status: ClaimStatus;
  user_note: string;
}

export interface ReviewDraft {
  draft_id: number;
  project_id: number;
  project_name: string;
  project_path: string;
  range_start: string;
  range_end: string;
  generated_at: string;
  exported_path: string | null;
  questions: string[];
  claims: ReviewClaim[];
}

export interface ConfirmResult {
  draft_id: number;
  changed: number;
  remaining_pending: number;
}

export interface ExportResult {
  path: string;
}
