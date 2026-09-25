"""DevLog 项目、事件与复盘草稿的 SQLite 状态存储。

设计规则：
- Git 是事实来源；本数据库只是缓存/状态存储。
- 数据库位于被扫描的仓库之外（默认 ~/.devlog/）。
- 插入是幂等的：同一 (project_id, hash) 只保存一次。
- 复盘草稿属于进行中的状态；只有导出的 Markdown 文件会进入用户仓库。
- 所有用户输入都通过参数化查询写入。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from devlog.core.capture.models import (
    AnnotationKind,
    BugRecord,
    BugStatus,
    CommitAnnotation,
    DailyNote,
)
from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.review.models import (
    ClaimStatus,
    ReviewClaim,
    ReviewDraft,
    ReviewQuestion,
)


SCHEMA_VERSION = 7

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

_SCHEMA_V3_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS commit_translations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        hash TEXT NOT NULL,
        translated_subject TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (project_id, hash),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_commit_translations_project_hash
        ON commit_translations (project_id, hash)
    """,
]

_SCHEMA_V4_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dev_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        note_date TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        issues TEXT NOT NULL DEFAULT '',
        plan TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, note_date),
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bug_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        title_source TEXT NOT NULL DEFAULT 'manual'
            CHECK (title_source IN ('manual', 'ai')),
        error_text TEXT NOT NULL DEFAULT '',
        environment TEXT NOT NULL DEFAULT '',
        git_head TEXT NOT NULL DEFAULT '',
        git_status TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'root_cause_found', 'resolved')),
        root_cause TEXT NOT NULL DEFAULT '',
        solution TEXT NOT NULL DEFAULT '',
        captured_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bug_records_project_status
        ON bug_records (project_id, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS commit_annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        commit_hash TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'note'
            CHECK (kind IN ('note', 'decision')),
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_commit_annotations_project_hash
        ON commit_annotations (project_id, commit_hash)
    """,
]

_SCHEMA_V5_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS draft_answers (
        draft_id INTEGER NOT NULL,
        question_number INTEGER NOT NULL,
        answer TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (draft_id, question_number),
        FOREIGN KEY (draft_id) REFERENCES review_drafts (id) ON DELETE CASCADE
    )
    """,
]

# 版本 5 -> 6：草稿记录自己是 AI 生成还是离线骨架。
# 可复用资产只有 AI 模式会归纳，前端需要这个字段才能把
# "AI 归纳过但没找到候选"和"离线模式根本没归纳"区分开。
# 老草稿留成 unknown，界面按中性文案处理。
_SCHEMA_V6_STATEMENTS = [
    """
    ALTER TABLE review_drafts
        ADD COLUMN generation_mode TEXT NOT NULL DEFAULT 'unknown'
    """,
]

# 版本 6 -> 7：草稿记录自己有没有"定稿"。
# 定稿只表示"这份复盘我认了、完成了"，不锁死内容——用户随时可以撤回继续改，
# 所以只需要一个状态列加一个时间戳，不必另建快照表。
# 老草稿留成 draft：它们从来没被定稿过，这个默认值就是事实。
_SCHEMA_V7_STATEMENTS = [
    """
    ALTER TABLE review_drafts
        ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'
    """,
    """
    ALTER TABLE review_drafts
        ADD COLUMN finalized_at TEXT
    """,
]

_COMMIT_COLUMNS = (
    "project_id, hash, short_hash, author_name, author_email, committed_at, "
    "message_subject, files_changed, insertions, deletions, parents_count, noise_type"
)


class DatabaseError(RuntimeError):
    """当状态数据库无法使用时抛出。"""


def _load_questions(raw: str | None) -> list[ReviewQuestion]:
    """读取草稿里的引导问题，兼容历史格式。

    schema v5 之前问题只存成字符串数组；从 v5 起存成
    {"section", "text"} 对象。老草稿必须还能打开，所以两种都要认。
    """

    items = json.loads(raw or "[]")
    questions: list[ReviewQuestion] = []
    for item in items:
        if isinstance(item, str):
            questions.append(ReviewQuestion(text=item))
        elif isinstance(item, dict):
            questions.append(
                ReviewQuestion(
                    text=str(item.get("text", "")),
                    section=str(item.get("section", "")),
                )
            )
    return questions


def default_db_path() -> Path:
    """返回本地数据库的默认位置。"""

    return Path.home() / ".devlog" / "devlog.db"


@dataclass(frozen=True)
class ProjectSummary:
    """一行已注册项目数据，供 API 与 CLI 列表使用。"""

    project_id: int
    name: str
    path: str
    created_at: datetime
    last_scanned_commit: str | None


@dataclass(frozen=True)
class ReviewDraftSummary:
    """供 `devlog review list` 使用的轻量行数据。"""

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
    # ai / offline / unknown：列表里要能一眼看出哪份是旧版本生成的。
    generation_mode: str = "unknown"
    # draft / finalized：定稿只表示"这份我认了"，可以随时撤回。
    status: str = "draft"
    finalized_at: datetime | None = None


@dataclass(frozen=True)
class StoredReviewClaim:
    """携带数据库 id 的已持久化论断。"""

    id: int
    claim: ReviewClaim


@dataclass(frozen=True)
class StoredReviewDraft:
    """已持久化的草稿，外加导出所需的项目上下文。"""

    draft_id: int
    project_id: int
    project_name: str
    project_path: str
    exported_path: str | None
    draft: ReviewDraft
    stored_claims: tuple[StoredReviewClaim, ...] = ()
    # draft / finalized，加定稿时间。定稿可以撤回，所以两者一起更新。
    status: str = "draft"
    finalized_at: datetime | None = None


@dataclass(frozen=True)
class StoredDailyNote:
    """携带数据库 id 与时间戳的已持久化每日笔记。"""

    id: int
    project_id: int
    note: DailyNote
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredBugRecord:
    """携带数据库 id 与时间戳的已持久化 Bug 捕获。"""

    id: int
    project_id: int
    bug: BugRecord
    captured_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredCommitAnnotation:
    """携带数据库 id 与时间戳的已持久化 commit 批注。"""

    id: int
    project_id: int
    annotation: CommitAnnotation
    created_at: datetime
    updated_at: datetime


class DevLogDB:
    """接口小而明确的轻量 SQLite 封装。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path is not None else default_db_path()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)

        # FastAPI 的依赖生成器与同步路由可能运行在不同的工作线程，
        # 因此这里允许连接跨线程使用（每个请求仍是独立的连接、串行访问）。
        self._conn = sqlite3.connect(
            str(path),
            timeout=5.0,
            check_same_thread=False,
        )
        self._closed = False
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema()
        except sqlite3.DatabaseError as exc:
            # 文件存在但不是 SQLite 库（或已损坏）时，连接必须自己关掉：
            # Windows 上句柄没释放，用户连这个坏文件都删不掉。
            self.close()
            raise DatabaseError(f"无法打开状态数据库：{exc}") from exc
        except Exception:
            self.close()
            raise

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
    # Schema 辅助
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        current = self.schema_version
        if current > SCHEMA_VERSION:
            raise DatabaseError(
                f"database schema version {current} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        if current < SCHEMA_VERSION:
            # 版本 0 -> 1 创建初始表。以后的版本在这里追加各自的迁移步骤，
            # 永远不要修改旧版本建表语句。
            if current == 0:
                for statement in _SCHEMA_V1_STATEMENTS:
                    self._conn.execute(statement)
            # 版本 1 -> 2 新增复盘草稿与论断表。
            if current < 2:
                for statement in _SCHEMA_V2_STATEMENTS:
                    self._conn.execute(statement)
            # 版本 2 -> 3 新增 AI commit 翻译缓存。
            if current < 3:
                for statement in _SCHEMA_V3_STATEMENTS:
                    self._conn.execute(statement)
            # 版本 3 -> 4 新增记忆层：每日笔记、Bug 捕获与 commit 批注。
            if current < 4:
                for statement in _SCHEMA_V4_STATEMENTS:
                    self._conn.execute(statement)
            # 版本 4 -> 5 新增引导问题的回答表。
            if current < 5:
                for statement in _SCHEMA_V5_STATEMENTS:
                    self._conn.execute(statement)
            # 版本 5 -> 6 记录草稿的生成方式（ai / offline / unknown）。
            if current < 6:
                for statement in _SCHEMA_V6_STATEMENTS:
                    self._conn.execute(statement)
            # 版本 6 -> 7 记录草稿有没有定稿（可撤回的标记，不是快照）。
            if current < 7:
                for statement in _SCHEMA_V7_STATEMENTS:
                    self._conn.execute(statement)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    # ------------------------------------------------------------------
    # 项目
    # ------------------------------------------------------------------

    def register_project(self, name: str, path: str | Path) -> int:
        """注册一个仓库。重复注册同一路径不会产生副作用。"""

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

    def list_projects(self) -> list[ProjectSummary]:
        """返回全部已注册项目，按最早注册的顺序排列。"""

        rows = self._conn.execute(
            "SELECT id, name, path, created_at, last_scanned_commit "
            "FROM projects ORDER BY id"
        ).fetchall()
        return [
            ProjectSummary(
                project_id=int(row[0]),
                name=row[1],
                path=row[2],
                created_at=datetime.fromisoformat(row[3]),
                last_scanned_commit=row[4],
            )
            for row in rows
        ]

    def get_project(self, project_id: int) -> ProjectSummary:
        """按 id 返回一个项目；不存在时抛出友好的 DatabaseError。"""

        row = self._conn.execute(
            "SELECT id, name, path, created_at, last_scanned_commit "
            "FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise DatabaseError(f"project not found: {project_id}")
        return ProjectSummary(
            project_id=int(row[0]),
            name=row[1],
            path=row[2],
            created_at=datetime.fromisoformat(row[3]),
            last_scanned_commit=row[4],
        )

    # ------------------------------------------------------------------
    # commit 事件
    # ------------------------------------------------------------------

    def save_events(self, project_id: int, events: list[CommitEvent]) -> int:
        """保存 commit 事件；重复项会被跳过。返回实际插入条数。"""

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
        """返回某个项目缓存的 commit 事件，最早提交的在前。

        默认隐藏噪音 commit。时间过滤是包含式的，并在 Python 中完成，
        这样混合时区偏移也能保持正确。
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
        """删除某项目的全部缓存事件（缓存可重新扫描生成）。"""

        cursor = self._conn.execute(
            "DELETE FROM commits WHERE project_id = ?", (project_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # commit 翻译（AI 生成的显示层）
    # ------------------------------------------------------------------

    def save_commit_translations(
        self,
        project_id: int,
        translations: dict[str, str],
    ) -> int:
        """按 (project_id, hash) 缓存 AI 翻译；返回实际插入数。"""

        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for commit_hash, text in translations.items():
            if not text.strip():
                continue
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO commit_translations "
                "(project_id, hash, translated_subject, created_at) "
                "VALUES (?, ?, ?, ?)",
                (project_id, commit_hash, text.strip(), now),
            )
            inserted += cursor.rowcount
        self._conn.commit()
        return inserted

    def list_commit_translations(
        self,
        project_id: int,
        hashes: list[str] | None = None,
    ) -> dict[str, str]:
        """返回某项目的翻译缓存（可按 hash 列表过滤）。"""

        if hashes is not None and not hashes:
            return {}

        sql = (
            "SELECT hash, translated_subject FROM commit_translations "
            "WHERE project_id = ?"
        )
        params: list[object] = [project_id]
        if hashes is not None:
            sql += " AND hash IN (" + ",".join("?" for _ in hashes) + ")"
            params.extend(hashes)

        rows = self._conn.execute(sql, params).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    # ------------------------------------------------------------------
    # 扫描游标
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
    # 复盘草稿
    # ------------------------------------------------------------------

    def save_review_draft(self, project_id: int, draft: ReviewDraft) -> int:
        """持久化一份生成的草稿及其全部论断；返回草稿 id。"""

        row = self._conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise DatabaseError(f"project does not exist: {project_id}")

        cursor = self._conn.execute(
            "INSERT INTO review_drafts "
            "(project_id, range_start, range_end, created_at, questions_json, "
            "generation_mode) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id,
                draft.range_start.isoformat(),
                draft.range_end.isoformat(),
                draft.generated_at.isoformat(),
                json.dumps(
                    [
                        {"section": question.section, "text": question.text}
                        for question in draft.questions
                    ],
                    ensure_ascii=False,
                ),
                draft.generation_mode,
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

    def save_draft_answer(
        self,
        draft_id: int,
        question_number: int,
        answer: str,
    ) -> str:
        """保存某条引导问题的回答，返回写入后的文本。

        问题编号从 1 开始，和导出文档里看到的编号一致 ——
        中间不做 0/1 转换，省得调用方各自 ±1 出错。
        """

        record = self.load_review_draft(draft_id)
        total = len(record.draft.questions)
        if total == 0:
            raise DatabaseError("this draft has no guidance questions")
        if question_number < 1 or question_number > total:
            raise DatabaseError(
                f"question number out of range: {question_number} (1..{total})"
            )

        self._conn.execute(
            "INSERT INTO draft_answers "
            "(draft_id, question_number, answer, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(draft_id, question_number) DO UPDATE SET "
            "answer = excluded.answer, updated_at = excluded.updated_at",
            (
                draft_id,
                question_number,
                answer,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return answer

    def _load_answers(self, draft_id: int) -> dict[int, str]:
        """读取草稿里所有已保存的回答，键是 1 起算的问题编号。"""

        rows = self._conn.execute(
            "SELECT question_number, answer FROM draft_answers "
            "WHERE draft_id = ?",
            (draft_id,),
        ).fetchall()
        return {int(number): text for number, text in rows}

    def list_review_drafts(
        self, project_id: int | None = None
    ) -> list[ReviewDraftSummary]:
        """返回草稿摘要（新的在前），可按项目过滤或返回全部。"""

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
        """加载一份草稿：包含项目上下文与按顺序排列的论断。"""

        row = self._conn.execute(
            "SELECT d.id, d.project_id, p.name, p.path, "
            "d.range_start, d.range_end, d.created_at, "
            "d.questions_json, d.exported_path, d.generation_mode "
            ", d.status, d.finalized_at "
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
        answers = self._load_answers(draft_id)
        questions = _load_questions(row[7])
        draft = ReviewDraft(
            project_name=row[2],
            range_start=datetime.fromisoformat(row[4]),
            range_end=datetime.fromisoformat(row[5]),
            claims=[item.claim for item in claims],
            questions=[
                ReviewQuestion(
                    text=question.text,
                    section=question.section,
                    answer=answers.get(number, ""),
                )
                for number, question in enumerate(questions, start=1)
            ],
            generated_at=created_at,
            generation_mode=row[9],
        )
        return StoredReviewDraft(
            draft_id=draft_id,
            project_id=int(row[1]),
            project_name=row[2],
            project_path=row[3],
            exported_path=row[8],
            draft=draft,
            stored_claims=tuple(claims),
            status=row[10] or "draft",
            finalized_at=(
                datetime.fromisoformat(row[11]) if row[11] else None
            ),
        )

    def confirm_review_claim(
        self,
        draft_id: int,
        claim_id: int,
        note: str | None = None,
    ) -> bool:
        """把一条 ai_pending 论断标记为已确认。事实论断不可修改。"""

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
        """确认某草稿中所有 ai_pending 论断。"""

        cursor = self._conn.execute(
            "UPDATE review_claims SET status = 'confirmed' "
            "WHERE draft_id = ? AND status = 'ai_pending'",
            (draft_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def set_review_finalized(self, draft_id: int, finalized: bool = True) -> str:
        """把草稿标成已定稿或撤回定稿，返回新状态。

        定稿只是"这份复盘我认了"的标记，不锁死内容：撤回之后照样能改论断、
        补回答、重新导出。要锁内容就得存快照，那是以后做"历次定稿对比"时
        才需要的事，现在不做。
        """

        if finalized:
            status = "finalized"
            stamp: str | None = datetime.now(timezone.utc).isoformat()
        else:
            status = "draft"
            stamp = None

        cursor = self._conn.execute(
            "UPDATE review_drafts SET status = ?, finalized_at = ? WHERE id = ?",
            (status, stamp, draft_id),
        )
        self._conn.commit()
        if cursor.rowcount != 1:
            raise DatabaseError(f"review draft not found: {draft_id}")
        return status

    def mark_draft_exported(self, draft_id: int, path: str | Path) -> None:
        """记录草稿最后导出到哪个文件。"""

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
            generation_mode=record.draft.generation_mode,
            status=record.status,
            finalized_at=record.finalized_at,
        )

    def delete_review_draft(self, draft_id: int) -> bool:
        """删除一份草稿及其论断与回答；存在时返回 True。

        论断（review_claims）和回答（draft_answers）都靠外键
        ON DELETE CASCADE 跟着删，不需要在这里手动清表。
        """

        cursor = self._conn.execute(
            "DELETE FROM review_drafts WHERE id = ?", (draft_id,)
        )
        self._conn.commit()
        return cursor.rowcount == 1

    # ------------------------------------------------------------------
    # 每日笔记（记忆层）
    # ------------------------------------------------------------------

    def upsert_daily_note(self, project_id: int, note: DailyNote) -> int:
        """插入或更新 (project, note_date) 对应的唯一一条笔记。"""

        self.get_project(project_id)
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO dev_notes
                (project_id, note_date, summary, issues, plan,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_id, note_date) DO UPDATE SET
                summary = excluded.summary,
                issues = excluded.issues,
                plan = excluded.plan,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                note.note_date.isoformat(),
                note.summary,
                note.issues,
                note.plan,
                now,
                now,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM dev_notes WHERE project_id = ? AND note_date = ?",
            (project_id, note.note_date.isoformat()),
        ).fetchone()
        return int(row[0])

    def get_daily_note(
        self,
        project_id: int,
        note_date: date,
    ) -> StoredDailyNote | None:
        """返回某一天的笔记；还没写时返回 None。"""

        row = self._conn.execute(
            "SELECT id, project_id, note_date, summary, issues, plan, "
            "created_at, updated_at FROM dev_notes "
            "WHERE project_id = ? AND note_date = ?",
            (project_id, note_date.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_daily_note(row)

    def list_daily_notes(
        self,
        project_id: int,
        since: date | None = None,
        until: date | None = None,
    ) -> list[StoredDailyNote]:
        """返回笔记（日期新的在前），可按日期范围过滤。"""

        sql = (
            "SELECT id, project_id, note_date, summary, issues, plan, "
            "created_at, updated_at FROM dev_notes WHERE project_id = ?"
        )
        params: list[object] = [project_id]
        if since is not None:
            sql += " AND note_date >= ?"
            params.append(since.isoformat())
        if until is not None:
            sql += " AND note_date <= ?"
            params.append(until.isoformat())
        sql += " ORDER BY note_date DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_daily_note(row) for row in rows]

    # ------------------------------------------------------------------
    # Bug 记录（记忆层）
    # ------------------------------------------------------------------

    def create_bug_record(self, project_id: int, bug: BugRecord) -> int:
        """持久化一条 Bug 现场快照并返回其 id。"""

        self.get_project(project_id)
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO bug_records
                (project_id, title, title_source, error_text, environment,
                 git_head, git_status, status, root_cause, solution,
                 captured_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                bug.title,
                bug.title_source,
                bug.error_text,
                bug.environment,
                bug.git_head,
                bug.git_status,
                bug.status.value,
                bug.root_cause,
                bug.solution,
                now,
                now,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_bug_record(self, bug_id: int) -> StoredBugRecord:
        """按 id 加载一条 Bug 记录；不存在时抛出友好的 DatabaseError。"""

        row = self._conn.execute(
            "SELECT id, project_id, title, title_source, error_text, "
            "environment, git_head, git_status, status, root_cause, "
            "solution, captured_at, updated_at "
            "FROM bug_records WHERE id = ?",
            (bug_id,),
        ).fetchone()
        if row is None:
            raise DatabaseError(f"bug record not found: {bug_id}")
        return self._row_to_bug_record(row)

    def list_bug_records(
        self,
        project_id: int,
        status: BugStatus | None = None,
    ) -> list[StoredBugRecord]:
        """返回 Bug 记录（新的在前），可按状态过滤。"""

        sql = (
            "SELECT id, project_id, title, title_source, error_text, "
            "environment, git_head, git_status, status, root_cause, "
            "solution, captured_at, updated_at "
            "FROM bug_records WHERE project_id = ?"
        )
        params: list[object] = [project_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY captured_at DESC, id DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_bug_record(row) for row in rows]

    def update_bug_record(
        self,
        bug_id: int,
        *,
        title: str | None = None,
        title_source: str | None = None,
        root_cause: str | None = None,
        solution: str | None = None,
        status: BugStatus | None = None,
    ) -> bool:
        """更新用户在 Bug 上补充的内容；现场快照保持不可变。"""

        if title_source is not None and title_source not in ("manual", "ai"):
            raise ValueError(f"unknown title_source: {title_source}")
        if status is not None and not isinstance(status, BugStatus):
            raise ValueError(f"unknown bug status: {status!r}")

        assignments: list[str] = []
        params: list[object] = []
        for column, value in (
            ("title", title),
            ("title_source", title_source),
            ("root_cause", root_cause),
            ("solution", solution),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(value)
        if status is not None:
            assignments.append("status = ?")
            params.append(status.value)
        if not assignments:
            raise ValueError("update_bug_record requires at least one field")

        assignments.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(bug_id)
        cursor = self._conn.execute(
            "UPDATE bug_records SET " + ", ".join(assignments) + " WHERE id = ?",
            params,
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def delete_bug_record(self, bug_id: int) -> bool:
        """删除一条 Bug 记录；存在时返回 True。"""

        cursor = self._conn.execute(
            "DELETE FROM bug_records WHERE id = ?", (bug_id,)
        )
        self._conn.commit()
        return cursor.rowcount == 1

    # ------------------------------------------------------------------
    # commit 批注（记忆层）
    # ------------------------------------------------------------------

    def add_commit_annotation(
        self,
        project_id: int,
        annotation: CommitAnnotation,
    ) -> int:
        """把一条批注挂到本项目已缓存的 commit 上。"""

        known = self._conn.execute(
            "SELECT id FROM commits WHERE project_id = ? AND hash = ?",
            (project_id, annotation.commit_hash),
        ).fetchone()
        if known is None:
            raise DatabaseError(
                f"commit hash not cached for project {project_id}: "
                f"{annotation.commit_hash}"
            )

        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO commit_annotations "
            "(project_id, commit_hash, kind, body, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id,
                annotation.commit_hash,
                annotation.kind.value,
                annotation.body,
                now,
                now,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_commit_annotation(
        self,
        annotation_id: int,
    ) -> StoredCommitAnnotation:
        """按 id 加载一条批注；不存在时抛出友好的 DatabaseError。"""

        row = self._conn.execute(
            "SELECT id, project_id, commit_hash, kind, body, "
            "created_at, updated_at FROM commit_annotations WHERE id = ?",
            (annotation_id,),
        ).fetchone()
        if row is None:
            raise DatabaseError(f"commit annotation not found: {annotation_id}")
        return self._row_to_annotation(row)

    def list_commit_annotations(
        self,
        project_id: int,
        commit_hash: str | None = None,
    ) -> list[StoredCommitAnnotation]:
        """返回某项目的批注（新的在前）。"""

        sql = (
            "SELECT id, project_id, commit_hash, kind, body, "
            "created_at, updated_at FROM commit_annotations "
            "WHERE project_id = ?"
        )
        params: list[object] = [project_id]
        if commit_hash is not None:
            sql += " AND commit_hash = ?"
            params.append(commit_hash)
        sql += " ORDER BY created_at DESC, id DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_annotation(row) for row in rows]

    def list_orphan_commit_annotations(
        self,
        project_id: int,
    ) -> list[StoredCommitAnnotation]:
        """返回 commit 在本项目中已不存在的批注。

        历史被改写（rebase / force push）可能移除原 hash；这些笔记会被
        保留并列出，而不是被悄悄丢失。
        """

        rows = self._conn.execute(
            """
            SELECT a.id, a.project_id, a.commit_hash, a.kind, a.body,
                   a.created_at, a.updated_at
            FROM commit_annotations a
            LEFT JOIN commits c
                ON c.project_id = a.project_id AND c.hash = a.commit_hash
            WHERE a.project_id = ? AND c.id IS NULL
            ORDER BY a.created_at DESC, a.id DESC
            """,
            (project_id,),
        ).fetchall()
        return [self._row_to_annotation(row) for row in rows]

    def update_commit_annotation(
        self,
        annotation_id: int,
        *,
        kind: AnnotationKind | None = None,
        body: str | None = None,
    ) -> bool:
        """编辑一条批注的 kind 或正文。"""

        assignments: list[str] = []
        params: list[object] = []
        if kind is not None:
            if not isinstance(kind, AnnotationKind):
                raise ValueError(f"unknown annotation kind: {kind!r}")
            assignments.append("kind = ?")
            params.append(kind.value)
        if body is not None:
            assignments.append("body = ?")
            params.append(body)
        if not assignments:
            raise ValueError("update_commit_annotation requires a field")

        assignments.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(annotation_id)
        cursor = self._conn.execute(
            "UPDATE commit_annotations SET "
            + ", ".join(assignments)
            + " WHERE id = ?",
            params,
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def delete_commit_annotation(self, annotation_id: int) -> bool:
        """删除一条批注；存在时返回 True。"""

        cursor = self._conn.execute(
            "DELETE FROM commit_annotations WHERE id = ?", (annotation_id,)
        )
        self._conn.commit()
        return cursor.rowcount == 1

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_event(row: sqlite3.Row | tuple) -> CommitEvent:
        # 列顺序：project_id, hash, short_hash, author_name, author_email,
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

    @staticmethod
    def _row_to_daily_note(row: sqlite3.Row | tuple) -> StoredDailyNote:
        # 列顺序：id, project_id, note_date, summary, issues, plan,
        # created_at, updated_at
        return StoredDailyNote(
            id=int(row[0]),
            project_id=int(row[1]),
            note=DailyNote(
                note_date=date.fromisoformat(row[2]),
                summary=row[3],
                issues=row[4],
                plan=row[5],
            ),
            created_at=datetime.fromisoformat(row[6]),
            updated_at=datetime.fromisoformat(row[7]),
        )

    @staticmethod
    def _row_to_bug_record(row: sqlite3.Row | tuple) -> StoredBugRecord:
        # 列顺序：id, project_id, title, title_source, error_text,
        # environment, git_head, git_status, status, root_cause, solution,
        # captured_at, updated_at
        return StoredBugRecord(
            id=int(row[0]),
            project_id=int(row[1]),
            bug=BugRecord(
                title=row[2],
                title_source=row[3],
                error_text=row[4],
                environment=row[5],
                git_head=row[6],
                git_status=row[7],
                status=BugStatus(row[8]),
                root_cause=row[9],
                solution=row[10],
            ),
            captured_at=datetime.fromisoformat(row[11]),
            updated_at=datetime.fromisoformat(row[12]),
        )

    @staticmethod
    def _row_to_annotation(row: sqlite3.Row | tuple) -> StoredCommitAnnotation:
        # 列顺序：id, project_id, commit_hash, kind, body, created_at,
        # updated_at
        return StoredCommitAnnotation(
            id=int(row[0]),
            project_id=int(row[1]),
            annotation=CommitAnnotation(
                commit_hash=row[2],
                kind=AnnotationKind(row[3]),
                body=row[4],
            ),
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
        )
