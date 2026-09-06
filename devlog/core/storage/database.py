"""SQLite state store for DevLog projects and cached commit events.

Design rules:
- Git is the source of truth; this database is only a cache/state store.
- The database lives outside scanned repositories (default ~/.devlog/).
- Inserts are idempotent: the same (project_id, hash) is stored once.
- All user-supplied values go through parameterized queries.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from devlog.core.git_source.models import CommitEvent, NoiseType


SCHEMA_VERSION = 1

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

_COMMIT_COLUMNS = (
    "project_id, hash, short_hash, author_name, author_email, committed_at, "
    "message_subject, files_changed, insertions, deletions, parents_count, noise_type"
)


class DatabaseError(RuntimeError):
    """Raised when the state database cannot be used."""


def default_db_path() -> Path:
    """Return the default local database location."""

    return Path.home() / ".devlog" / "devlog.db"


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
