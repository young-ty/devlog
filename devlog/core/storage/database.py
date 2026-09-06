"""SQLite state store for DevLog projects, events and review drafts.

Design rules:
- Git is the source of truth; this database is only a cache/state store.
- The database lives outside scanned repositories (default ~/.devlog/).
- Inserts are idempotent: the same (project_id, hash) is stored once.
- Review drafts are work-in-progress state; only the exported Markdown
  file enters the user's repository.
- All user-supplied values go through parameterized queries.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.review.models import (
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
)


SCHEMA_VERSION = 2

_SCHEMA_V1_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        last_scanned_commit TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        hash TEXT NOT NULL,
        short_hash TEXT NOT NULL,
        author_name TEXT NOT NULL,
        author_email TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        message_subject TEXT NOT NULL,
        files_changed INTEGER NOT NULL,
        insertions INTEGER NOT NULL,
        deletions INTEGER NOT NULL,
        parents_count INTEGER NOT NULL,
        noise_type TEXT NOT NULL,
        UNIQUE (project_id, hash),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_commits_project_time
        ON commits (project_id, committed_at)
    """,
]

_SCHEMA_V2_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS review_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        range_start TEXT NOT NULL,
        range_end TEXT NOT NULL,
        created_at TEXT NOT NULL,
        questions_json TEXT NOT NULL DEFAULT '[]',
        exported_path TEXT,
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        section TEXT NOT NULL,
        text TEXT NOT NULL,
        sources_json TEXT NOT NULL,
        status TEXT NOT NULL,
        user_note TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (draft_id) REFERENCES review_drafts (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_review_claims_draft
        ON review_claims (draft_id, position)
    """,
]

_COMMIT_COLUMNS = (
    "project_id, hash, short_hash, author_name, author_email, committed_at, "
    "message_subject, files_changed, insertions, deletions, parents_count, noise_type"
)


class DatabaseError(RuntimeError):
    """Raised when the state database cannot be used."""


def default_db_path() -> Path:
    """Return the default local database location."""

    return Path.home() / ".devlog" / "devlog.db"


@dataclass(frozen=True)
class ReviewDraftSummary:
    """Lightweight row used by `devlog review list`."""

    draft_id: int
    project_id: int
    project_name: str
    project_path: str
    range_start: datetime
    range_end: datetime
    created_at: datetime
    total_claims: int
    ai_pending_claims: int
    confirmed_claims: int


@dataclass(frozen=True)
class StoredReviewClaim:
    """A persisted claim carrying its database id."""

    id: int
    claim: ReviewClaim


@dataclass(frozen=True)
class StoredReviewDraft:
    """A persisted draft plus the project context needed to export it."""

    draft_id: int
    project_id: int
    project_name: str
    project_path: str
    exported_path: str | None
    draft: ReviewDraft
    stored_claims: tuple[StoredReviewClaim, ...] = ()


class DevLogDB:
    """Thin SQLite wrapper with an explicit, small API."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path is not None else default_db_path()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(path), timeout=5.0)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()
        self._closed = False

    @property
    def schema_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    def __enter__(self) -> "DevLogDB":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        current = self.schema_version
        if current > SCHEMA_VERSION:
            raise DatabaseError(
                f"database schema version {current} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        if current < SCHEMA_VERSION:
            # Version 0 -> 1 creates the initial tables. Future versions
            # append their own migration steps here, never edit old ones.
            if current == 0:
                for statement in _SCHEMA_V1_STATEMENTS:
                    self._conn.execute(statement)
            # Version 1 -> 2 adds review draft and claim tables.
            if current < 2:
                for statement in _SCHEMA_V2_STATEMENTS:
                    self._conn.execute(statement)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def register_project(self, name: str, path: str | Path) -> int:
        """Register a repository. Registering the same path again is a no-op."""

        resolved = str(Path(path).expanduser().resolve())
        existing = self._conn.execute(
            "SELECT id FROM projects WHERE path = ?", (resolved,)
        ).fetchone()
        if existing is not None:
            return int(existing[0])

        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO projects (name, path, created_at) VALUES (?, ?, ?)",
            (name, resolved, created_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------

    def save_events(self, project_id: int, events: list[CommitEvent]) -> int:
        """Store commit events; duplicates are skipped. Returns inserted count."""

        sql = (
            f"INSERT OR IGNORE INTO commits ({_COMMIT_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        inserted = 0
        for event in events:
            cursor = self._conn.execute(
                sql,
                (
                    project_id,
                    event.hash,
                    event.short_hash,
                    event.author_name,
                    event.author_email,
                    event.committed_at.isoformat(),
                    event.message_subject,
                    event.files_changed,
                    event.insertions,
                    event.deletions,
                    event.parents_count,
                    event.noise_type.value,
                ),
            )
            inserted += cursor.rowcount
        self._conn.commit()
        return inserted

    def list_events(
        self,
        project_id: int,
        since: datetime | None = None,
        until: datetime | None = None,
        include_noise: bool = False,
    ) -> list[CommitEvent]:
        """Return cached events for a project, oldest first.

        Noise commits are hidden by default. Time filtering is inclusive
        and performed in Python so mixed timezone offsets stay correct.
        """

        sql = "SELECT " + _COMMIT_COLUMNS + " FROM commits WHERE project_id = ?"
        params: list[object] = [project_id]
        if not include_noise:
            sql += " AND noise_type = 'none'"

        rows = self._conn.execute(sql, params).fetchall()
        events = [self._row_to_event(row) for row in rows]

        if since is not None:
            events = [event for event in events if event.committed_at >= since]
        if until is not None:
            events = [event for event in events if event.committed_at <= until]
        events.sort(key=lambda event: event.committed_at)
        return events

    def clear_events(self, project_id: int) -> int:
        """Delete all cached events for a project (cache can be rebuilt)."""

        cursor = self._conn.execute(
            "DELETE FROM commits WHERE project_id = ?", (project_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Scan cursor
    # ------------------------------------------------------------------

    def update_scan_cursor(self, project_id: int, commit_hash: str) -> None:
        self._conn.execute(
            "UPDATE projects SET last_scanned_commit = ? WHERE id = ?",
            (commit_hash, project_id),
        )
        self._conn.commit()

    def get_scan_cursor(self, project_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT last_scanned_commit FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return None if row is None else row[0]

    # ------------------------------------------------------------------
    # Review drafts
    # ------------------------------------------------------------------

    def save_review_draft(self, project_id: int, draft: ReviewDraft) -> int:
        """Persist a generated draft with all claims; returns the draft id."""

        row = self._conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise DatabaseError(f"project does not exist: {project_id}")

        cursor = self._conn.execute(
            "INSERT INTO review_drafts "
            "(project_id, range_start, range_end, created_at, questions_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                project_id,
                draft.range_start.isoformat(),
                draft.range_end.isoformat(),
                draft.generated_at.isoformat(),
                json.dumps(draft.questions, ensure_ascii=False),
            ),
        )
        draft_id = int(cursor.lastrowid)

        for position, claim in enumerate(draft.claims):
            self._conn.execute(
                "INSERT INTO review_claims "
                "(draft_id, position, section, text, sources_json, status, user_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    draft_id,
                    position,
                    claim.section,
                    claim.text,
                    json.dumps(list(claim.sources)),
                    claim.status.value,
                    claim.user_note,
                ),
            )
        self._conn.commit()
        return draft_id

    def list_review_drafts(
        self, project_id: int | None = None
    ) -> list[ReviewDraftSummary]:
        """Return draft summaries, newest first, for one project or all."""

        if project_id is None:
            rows = self._conn.execute(
                "SELECT id FROM review_drafts ORDER BY id DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id FROM review_drafts WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()

        records = [self.load_review_draft(int(row[0])) for row in rows]
        return [self._summarize_draft(record) for record in records]

    def load_review_draft(self, draft_id: int) -> StoredReviewDraft:
        """Load one draft with project context and ordered claims."""

        row = self._conn.execute(
            "SELECT d.id, d.project_id, p.name, p.path, "
            "d.range_start, d.range_end, d.created_at, "
            "d.questions_json, d.exported_path "
            "FROM review_drafts d "
            "JOIN projects p ON p.id = d.project_id "
            "WHERE d.id = ?",
            (draft_id,),
        ).fetchone()
        if row is None:
            raise DatabaseError(f"review draft not found: {draft_id}")

        claims: list[StoredReviewClaim] = []
        for claim_id, section, text, sources_json, status, user_note in self._conn.execute(
            "SELECT id, section, text, sources_json, status, user_note "
            "FROM review_claims WHERE draft_id = ? ORDER BY position",
            (draft_id,),
        ):
            claims.append(
                StoredReviewClaim(
                    id=int(claim_id),
                    claim=ReviewClaim(
                        section=section,
                        text=text,
                        sources=tuple(json.loads(sources_json)),
                        status=ClaimStatus(status),
                        user_note=user_note,
                    ),
                )
            )

        created_at = datetime.fromisoformat(row[6])
        draft = ReviewDraft(
            project_name=row[2],
            range_start=datetime.fromisoformat(row[4]),
            range_end=datetime.fromisoformat(row[5]),
            claims=[item.claim for item in claims],
            questions=json.loads(row[7] or "[]"),
            generated_at=created_at,
        )
        return StoredReviewDraft(
            draft_id=draft_id,
            project_id=int(row[1]),
            project_name=row[2],
            project_path=row[3],
            exported_path=row[8],
            draft=draft,
            stored_claims=tuple(claims),
        )

    def confirm_review_claim(
        self,
        draft_id: int,
        claim_id: int,
        note: str | None = None,
    ) -> bool:
        """Mark one ai_pending claim as confirmed. Facts cannot be changed."""

        sql = "UPDATE review_claims SET status = 'confirmed'"
        params: list[object] = []
        if note is not None:
            sql += ", user_note = ?"
            params.append(note)
        sql += " WHERE id = ? AND draft_id = ? AND status = 'ai_pending'"
        params.extend([claim_id, draft_id])

        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount == 1

    def confirm_all_ai_claims(self, draft_id: int) -> int:
        """Confirm every ai_pending claim in a draft."""

        cursor = self._conn.execute(
            "UPDATE review_claims SET status = 'confirmed' "
            "WHERE draft_id = ? AND status = 'ai_pending'",
            (draft_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def mark_draft_exported(self, draft_id: int, path: str | Path) -> None:
        """Remember where the draft was last exported."""

        self._conn.execute(
            "UPDATE review_drafts SET exported_path = ? WHERE id = ?",
            (str(Path(path).resolve()), draft_id),
        )
        self._conn.commit()

    @staticmethod
    def _summarize_draft(record: StoredReviewDraft) -> ReviewDraftSummary:
        pending = sum(
            1
            for item in record.draft.claims
            if item.status == ClaimStatus.AI_PENDING
        )
        confirmed = sum(
            1
            for item in record.draft.claims
            if item.status == ClaimStatus.CONFIRMED
        )
        return ReviewDraftSummary(
            draft_id=record.draft_id,
            project_id=record.project_id,
            project_name=record.project_name,
            project_path=record.project_path,
            range_start=record.draft.range_start,
            range_end=record.draft.range_end,
            created_at=record.draft.generated_at,
            total_claims=len(record.draft.claims),
            ai_pending_claims=pending,
            confirmed_claims=confirmed,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_event(row: sqlite3.Row | tuple) -> CommitEvent:
        # Columns: project_id, hash, short_hash, author_name, author_email,
        # committed_at, message_subject, files_changed, insertions,
        # deletions, parents_count, noise_type
        return CommitEvent(
            hash=row[1],
            short_hash=row[2],
            author_name=row[3],
            author_email=row[4],
            committed_at=datetime.fromisoformat(row[5]),
            message_subject=row[6],
            files_changed=int(row[7]),
            insertions=int(row[8]),
            deletions=int(row[9]),
            parents_count=int(row[10]),
            noise_type=NoiseType(row[11]),
        )
