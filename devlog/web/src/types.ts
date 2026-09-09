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

export type NoiseType = "none" | "merge" | "revert" | "wip" | "chore";

export interface TimelineCommit {
  hash: string;
  short_hash: string;
  author_name: string;
  author_email: string;
  committed_at: string;
  message_subject: string;
  files_changed: number;
  insertions: number;
  deletions: number;
  parents_count: number;
  noise_type: NoiseType;
  translated_subject: string | null;
}

export interface TimelineTheme {
  id: string;
  title: string;
  kind: string;
  commit_hashes: string[];
  started_at: string;
  ended_at: string;
  commit_count: number;
  is_milestone_candidate: boolean;
}

export interface TimelineSilencePeriod {
  started_at: string;
  ended_at: string;
  days: number;
}

export interface ProjectTimeline {
  project_id: number;
  project_name: string;
  project_path: string;
  range_start: string | null;
  range_end: string | null;
  commits: TimelineCommit[];
  themes: TimelineTheme[];
  silence_periods: TimelineSilencePeriod[];
}

export interface TranslationResult {
  project_id: number;
  project_name: string;
  project_path: string;
  translated_count: number;
  remaining_count: number;
}

export interface LLMConfig {
  configured: boolean;
  model: string;
  base_url: string;
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

export type BugStatus = "open" | "root_cause_found" | "resolved";
export type BugTitleSource = "manual" | "ai";

export interface DailyNote {
  id: number;
  project_id: number;
  note_date: string;
  summary: string;
  issues: string;
  plan: string;
  created_at: string;
  updated_at: string;
}

export interface DailyNoteInput {
  note_date: string;
  summary: string;
  issues: string;
  plan: string;
}

export interface BugRecord {
  id: number;
  project_id: number;
  title: string;
  title_source: BugTitleSource;
  error_text: string;
  environment: string;
  git_head: string;
  git_status: string;
  status: BugStatus;
  root_cause: string;
  solution: string;
  captured_at: string;
  updated_at: string;
}

export interface BugCaptureInput {
  title?: string;
  title_source?: BugTitleSource;
  error_text: string;
}

export interface BugUpdateInput {
  title?: string;
  title_source?: BugTitleSource;
  root_cause?: string;
  solution?: string;
  status?: BugStatus;
}

export interface SuggestTitleInput {
  error_text: string;
  environment?: string;
}

export interface SuggestTitleResult {
  title: string;
}

export type AnnotationKind = "note" | "decision";

export interface CommitAnnotation {
  id: number;
  project_id: number;
  commit_hash: string;
  kind: AnnotationKind;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface AnnotationCreateInput {
  kind: AnnotationKind;
  body: string;
}

export interface AnnotationUpdateInput {
  kind?: AnnotationKind;
  body?: string;
}
