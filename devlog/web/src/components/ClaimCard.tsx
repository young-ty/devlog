import { useState, type FormEvent } from "react";
import type { ReviewClaim } from "../types";
import { StatusBadge } from "./StatusBadge";

interface ClaimCardProps {
  claim: ReviewClaim;
  onConfirm: (claimId: number, note?: string) => Promise<void>;
}

export function ClaimCard({ claim, onConfirm }: ClaimCardProps) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onConfirm(claim.id, note);
    } finally {
      setBusy(false);
    }
  }

  const shownSources = claim.sources.slice(0, 3);

  return (
    <article className="claim">
      <header className="claim-header">
        <StatusBadge status={claim.status} />
        <span className="claim-section">{claim.section}</span>
      </header>
      <p className="claim-text">{claim.text}</p>
      {shownSources.length > 0 && (
        <p className="claim-sources">
          来源：
          {shownSources.map((source) => (
            <code key={source}>{source.slice(0, 7)}</code>
          ))}
          {claim.sources.length > 3 && (
            <span>等 {claim.sources.length} 个提交</span>
          )}
        </p>
      )}
      {claim.status === "ai_pending" && (
        <form className="confirm-form" onSubmit={handleSubmit}>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="可选：补充说明后确认"
          />
          <button type="submit" disabled={busy}>
            {busy ? "确认中…" : "确认这条"}
          </button>
        </form>
      )}
    </article>
  );
}
