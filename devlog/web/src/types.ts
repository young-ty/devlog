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

export interface DirectoryPickResult {
  cancelled: boolean;
  path: string | null;
  is_git_repo: boolean;
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
  /** 本次归纳出的可复用资产候选数；离线模式恒为 0。 */
  asset_count: number;
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
  /** ai / offline / unknown：unknown 是旧版本生成的草稿。 */
  generation_mode: string;
}

export interface ReviewClaim {
  id: number;
  section: string;
  text: string;
  sources: string[];
  status: ClaimStatus;
  user_note: string;
}

export interface ReviewQuestion {
  text: string;
  section: string;
  answer: string;
}

export interface ReviewDraft {
  draft_id: number;
  project_id: number;
  project_name: string;
  project_path: string;
  range_start: string;
  range_end: string;
  generated_at: string;
  /** ai / offline / unknown：unknown 表示这次改动之前生成的历史草稿。 */
  generation_mode: string;
  exported_path: string | null;
  questions: ReviewQuestion[];
  claims: ReviewClaim[];
}

export interface FinalClaim {
  text: string;
  status: ClaimStatus;
  sources: string[];
  user_note: string;
}

export interface FinalAnswer {
  question_number: number;
  question: string;
  answer: string;
}

export interface FinalSection {
  title: string;
  /** 图标名，和 Icons 组件同名；后端说了算，前端只负责画。 */
  icon: string;
  claims: FinalClaim[];
  answers: FinalAnswer[];
  open_questions: string[];
  hint: string;
  count: number;
  is_empty: boolean;
}

/** 成稿：只收人类认过的内容，未确认的 AI 推断单独放在 pending 里。 */
export interface FinalDocument {
  draft_id: number;
  title: string;
  project_name: string;
  project_path: string;
  range_start: string;
  range_end: string;
  generated_at: string;
  generation_mode: string;
  sections: FinalSection[];
  pending: FinalClaim[];
  included_count: number;
  pending_count: number;
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

/** 时间线节点承载的是哪一类事实。 */
export type TimelineEventKind =
  | "commit"
  | "bug"
  | "note"
  | "annotation"
  | "milestone"
  | "gap";

/** 时间线上的一个节点。payload 字段按 kind 取用。
 *
 * 后端把六种来源合并成同一种形状，是为了让前端只写一套排版逻辑；
 * 代价是每种事件只能读自己那一格，读错格子会拿到 null。
 */
export interface TimelineEvent {
  kind: TimelineEventKind;
  at: string;
  key: string;
  commit: TimelineCommit | null;
  bug: BugRecord | null;
  note: DailyNote | null;
  annotation: CommitAnnotation | null;
  theme: TimelineTheme | null;
  gap: TimelineSilencePeriod | null;
}

export interface TimelineStream {
  project_id: number;
  project_name: string;
  project_path: string;
  total_count: number;
  /** 因为超过上限而没有画到时间线上的更早事件数量。 */
  truncated_count: number;
  /** 原 commit 已不在历史中的批注数量；这些批注不进时间线。 */
  orphan_annotation_count: number;
  events: TimelineEvent[];
}
