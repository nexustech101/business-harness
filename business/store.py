"""business/store.py

The workspace's system of record: one SQLite file (`business.database`), shared with `ConnectorHub`, which
keeps its own tables in it. Every row belongs to an owner (`api.deps.business_owner`: the API key id) and
every query filters on it.

    business_meta         schema version of these tables (not PRAGMA user_version: the file is shared)
    profiles              one BusinessProfile (JSON) per owner
    answers               interview answers, one per (owner, question id)
    organized_documents   library documents placed in the profile: department, kind, summary
    assistants            AssistantSpec (JSON), status, created_by; name unique per owner (case-insensitive)
    approvals             queued write calls of assistants and their outcome
    notes                 the shared notes board: topic, text, author
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from business.errors import OutdatedWorkspace
from business.schema import Answer, Approval, AssistantInfo, AssistantSpec, Note, OrganizedDocument

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS business_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS profiles (
    owner TEXT PRIMARY KEY,
    profile TEXT NOT NULL,  -- BusinessProfile JSON
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    owner TEXT NOT NULL,
    question_id TEXT NOT NULL,
    answer TEXT NOT NULL,
    answered_at TEXT NOT NULL,
    PRIMARY KEY (owner, question_id)
);

CREATE TABLE IF NOT EXISTS organized_documents (
    owner TEXT NOT NULL,
    document_id TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    organized_at TEXT NOT NULL,
    PRIMARY KEY (owner, document_id)
);

CREATE TABLE IF NOT EXISTS assistants (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    spec TEXT NOT NULL,  -- AssistantSpec JSON
    status TEXT NOT NULL,  -- draft | active | paused
    created_by TEXT NOT NULL,  -- owner | partner
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner, name)
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    assistant_id TEXT NOT NULL,
    assistant_name TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,  -- JSON
    reason TEXT NOT NULL,
    status TEXT NOT NULL,  -- pending | executing | rejected | executed | failed
    result TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    seq INTEGER PRIMARY KEY,  -- insertion order: newest first without relying on equal timestamps
    id TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL,
    topic TEXT NOT NULL COLLATE NOCASE,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approvals_owner ON approvals(owner, status, created_at);
CREATE INDEX IF NOT EXISTS idx_notes_owner_topic ON notes(owner, topic);
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def _assistant(row: sqlite3.Row) -> AssistantInfo:
    return AssistantInfo(**json.loads(row["spec"]), id=row["id"], status=row["status"], created_by=row["created_by"],
                         created_at=row["created_at"], updated_at=row["updated_at"])


def _approval(row: sqlite3.Row) -> Approval:
    return Approval(**{k: row[k] for k in row.keys() if k not in ("owner", "arguments")},  # noqa: SIM118
                    arguments=json.loads(row["arguments"]))


def _note(row: sqlite3.Row) -> Note:
    return Note(id=row["id"], topic=row["topic"], text=row["text"], author=row["author"], created_at=row["created_at"])


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._ready = False
        self._lock = threading.Lock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection per operation, committed on success; the tables are created on first use."""
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.path) as conn:
                    meta = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'business_meta'").fetchone()
                    row = meta and conn.execute(
                        "SELECT value FROM business_meta WHERE key = 'schema_version'").fetchone()
                    if row and int(row[0]) != SCHEMA_VERSION:  # checked before any table is created or changed
                        raise OutdatedWorkspace(f"{self.path} holds workspace tables of version {row[0]}; this "
                                                f"version needs {SCHEMA_VERSION}. Set another business.database.")
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.executescript(SCHEMA)
                    conn.execute("INSERT OR IGNORE INTO business_meta VALUES ('schema_version', ?)",
                                 (str(SCHEMA_VERSION),))
                self._ready = True
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # --- profile and answers -----------------------------------------------------------------

    def profile(self, owner: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT profile FROM profiles WHERE owner = ?", (owner,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_profile(self, owner: str, profile: dict) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO profiles VALUES (?, ?, ?) ON CONFLICT (owner) DO UPDATE SET"
                         " profile = excluded.profile, updated_at = excluded.updated_at",
                         (owner, json.dumps(profile), now()))

    def answers(self, owner: str) -> dict[str, Answer]:
        with self.connect() as conn:
            rows = conn.execute("SELECT question_id, answer, answered_at FROM answers WHERE owner = ?"
                                " ORDER BY answered_at", (owner,)).fetchall()
        return {r["question_id"]: Answer(**dict(r)) for r in rows}

    def save_answer(self, owner: str, question_id: str, answer: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO answers VALUES (?, ?, ?, ?) ON CONFLICT (owner, question_id) DO UPDATE SET"
                         " answer = excluded.answer, answered_at = excluded.answered_at",
                         (owner, question_id, answer, now()))

    # --- organized documents -------------------------------------------------------------------

    def organized(self, owner: str) -> list[OrganizedDocument]:
        with self.connect() as conn:
            rows = conn.execute("SELECT document_id, title, department, kind, summary, organized_at"
                                " FROM organized_documents WHERE owner = ? ORDER BY organized_at DESC",
                                (owner,)).fetchall()
        return [OrganizedDocument(**dict(r)) for r in rows]

    def organize(self, owner: str, document: OrganizedDocument) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO organized_documents VALUES (?, ?, ?, ?, ?, ?, ?)"
                         " ON CONFLICT (owner, document_id) DO UPDATE SET title = excluded.title,"
                         " department = excluded.department, kind = excluded.kind, summary = excluded.summary,"
                         " organized_at = excluded.organized_at",
                         (owner, document.document_id, document.title, document.department, document.kind,
                          document.summary, document.organized_at.isoformat()))

    # --- assistants -------------------------------------------------------------------------------

    def assistants(self, owner: str) -> list[AssistantInfo]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM assistants WHERE owner = ? ORDER BY name", (owner,)).fetchall()
        return [_assistant(r) for r in rows]

    def assistant(self, owner: str, assistant_id: str) -> AssistantInfo | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM assistants WHERE owner = ? AND id = ?", (owner, assistant_id)).fetchone()
        return _assistant(row) if row else None

    def insert_assistant(self, owner: str, spec: AssistantSpec, created_by: str) -> str:
        """The new id; `sqlite3.IntegrityError` for a duplicate name."""
        assistant_id, at = str(uuid.uuid4()), now()
        with self.connect() as conn:
            conn.execute("INSERT INTO assistants VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
                         (assistant_id, owner, spec.name, spec.model_dump_json(), created_by, at, at))
        return assistant_id

    def update_assistant(self, owner: str, assistant_id: str, spec: AssistantSpec, status: str | None = None) -> bool:
        """Replace the spec (and the status when given); `sqlite3.IntegrityError` for a duplicate name."""
        with self.connect() as conn:
            cursor = conn.execute("UPDATE assistants SET name = ?, spec = ?, status = coalesce(?, status),"
                                  " updated_at = ? WHERE owner = ? AND id = ?",
                                  (spec.name, spec.model_dump_json(), status, now(), owner, assistant_id))
        return cursor.rowcount == 1

    def set_status(self, owner: str, assistant_id: str, status: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("UPDATE assistants SET status = ?, updated_at = ? WHERE owner = ? AND id = ?",
                                  (status, now(), owner, assistant_id))
        return cursor.rowcount == 1

    def delete_assistant(self, owner: str, assistant_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM assistants WHERE owner = ? AND id = ?", (owner, assistant_id))
        return cursor.rowcount == 1

    # --- approvals ----------------------------------------------------------------------------------

    def approvals(self, owner: str, status: str | None = None) -> list[Approval]:
        sql = "SELECT * FROM approvals WHERE owner = ?" + (" AND status = ?" if status else "")
        with self.connect() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC", (owner, status) if status else (owner,)).fetchall()
        return [_approval(r) for r in rows]

    def approval(self, owner: str, approval_id: str) -> Approval | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE owner = ? AND id = ?", (owner, approval_id)).fetchone()
        return _approval(row) if row else None

    def insert_approval(self, owner: str, assistant: AssistantInfo, connector_id: str, tool: str, arguments: dict,
                        reason: str) -> str:
        approval_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute("INSERT INTO approvals (id, owner, assistant_id, assistant_name, connector_id, tool,"
                         " arguments, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                         (approval_id, owner, assistant.id, assistant.name, connector_id, tool, json.dumps(arguments),
                          reason, now()))
        return approval_id

    def decide(self, owner: str, approval_id: str, status: str, result: str | None, decided_by: str,
               note: str | None, current: str = "pending") -> bool:
        """Move an approval from `current` to `status` in one statement; False when it is not `current` (another
        decision got there first). `pending -> executing` claims it before its call runs."""
        with self.connect() as conn:
            cursor = conn.execute("UPDATE approvals SET status = ?, result = ?, decided_at = ?, decided_by = ?,"
                                  " note = ? WHERE owner = ? AND id = ? AND status = ?",
                                  (status, result, now(), decided_by, note, owner, approval_id, current))
        return cursor.rowcount == 1

    # --- notes ------------------------------------------------------------------------------------------

    def notes(self, owner: str, topics: list[str] | None = None, limit: int = 200) -> list[Note]:
        """Newest first; `topics`: only these (case-insensitive), None: every topic."""
        sql, params = "SELECT * FROM notes WHERE owner = ?", [owner]
        if topics is not None:
            sql += f" AND topic IN ({','.join('?' * len(topics))})"
            params += topics
        with self.connect() as conn:
            rows = conn.execute(sql + " ORDER BY seq DESC LIMIT ?", [*params, limit]).fetchall()
        return [_note(r) for r in rows]

    def insert_note(self, owner: str, topic: str, text: str, author: str) -> Note:
        note_id, at = str(uuid.uuid4()), now()
        with self.connect() as conn:
            conn.execute("INSERT INTO notes (id, owner, topic, text, author, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                         (note_id, owner, topic, text, author, at))
        return Note(id=note_id, topic=topic, text=text, author=author, created_at=at)
