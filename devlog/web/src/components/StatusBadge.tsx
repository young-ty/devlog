import type { ClaimStatus } from "../types";

const LABELS: Record<ClaimStatus, string> = {
  fact: "事实",
  ai_pending: "AI 待确认",
  confirmed: "已确认",
  edited: "已修改",
};

export function StatusBadge({ status }: { status: ClaimStatus }) {
  return <span className={`badge badge-${status}`}>{LABELS[status]}</span>;
}
