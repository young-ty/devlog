"""Scan a local Git repository and return normalized CommitEvent items."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from devlog.core.git_source.models import CommitEvent, NoiseType


RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


class GitSourceError(RuntimeError):
    """Raised when a repository cannot be scanned."""


def _classify_noise(subject: str, parents_count: int) -> NoiseType:
    """Classify low-signal commits (merge/revert/wip/chore)."""

    if parents_count > 1:
        return NoiseType.MERGE

    lowered = subject.strip().lower()
    if lowered.startswith(("wip:", "[wip]")):
        return NoiseType.WIP
    if lowered.startswith(("chore:", "[chore]")):
        return NoiseType.CHORE
    if lowered.startswith(("revert:", "revert ", "[revert]")):
        return NoiseType.REVERT
    return NoiseType.NONE


def _parse_git_log_output(output: str) -> list[CommitEvent]:
    """Parse combined git log (format + numstat) output into events."""

    events: list[CommitEvent] = []
    for chunk in output.split(RECORD_SEP):
        chunk = chunk.strip("\r\n")
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue

        fields = lines[0].split(FIELD_SEP)
        if len(fields) < 7:
            continue

        commit_hash, short_hash, author_name, author_email = fields[0:4]
        iso_time = fields[4]
        subject = fields[5]
        parents = fields[6]

        try:
            committed_at = datetime.fromisoformat(iso_time)
        except ValueError:
            continue

        parents_count = len(parents.split()) if parents else 0
        files_changed = 0
        insertions = 0
        deletions = 0

        # Remaining lines are numstat entries: "<added>\t<removed>\t<path>"
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added, removed = parts[0], parts[1]
            files_changed += 1
            if added.isdigit():
                insertions += int(added)
            if removed.isdigit():
                deletions += int(removed)

        events.append(
            CommitEvent(
                hash=commit_hash,
                short_hash=short_hash,
                author_name=author_name,
                author_email=author_email,
                committed_at=committed_at,
                message_subject=subject,
                files_changed=files_changed,
                insertions=insertions,
                deletions=deletions,
                parents_count=parents_count,
                noise_type=_classify_noise(subject, parents_count),
            )
        )
    return events


def scan_repository(
    repo_path: str | Path,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[CommitEvent]:
    """Return all commits of a repository as CommitEvent, oldest first.

    since/until filter on the commit timestamp (inclusive). Both values
    should be timezone-aware to compare reliably with git timestamps.
    """

    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        raise GitSourceError(f"path does not exist: {repo}")

    format_spec = (
        RECORD_SEP
        + "%H" + FIELD_SEP
        + "%h" + FIELD_SEP
        + "%an" + FIELD_SEP
        + "%ae" + FIELD_SEP
        + "%aI" + FIELD_SEP
        + "%s" + FIELD_SEP
        + "%P"
    )
    command = [
        "git",
        "-C",
        str(repo),
        "log",
        "--reverse",
        "--no-decorate",
        "--numstat",
        f"--format={format_spec}",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise GitSourceError("git executable not found; please install git") from exc

    if result.returncode != 0:
        detail = (result.stderr or "unknown error").strip()
        if "does not have any commits yet" in detail.lower():
            return []
        raise GitSourceError(f"failed to read git repository: {detail}")

    events = _parse_git_log_output(result.stdout)
    if since is not None:
        events = [event for event in events if event.committed_at >= since]
    if until is not None:
        events = [event for event in events if event.committed_at <= until]
    return events
