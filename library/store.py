"""library/store.py

The library's system of record: one SQLite file (`library.database`).

    documents        one row per uploaded file or workspace record: title, type, media type, page sizes, hash,
                     location, owner (API key id)
    document_chunks  searchable passages: text, section title, page/sheet, embedding (float32 blob,
                     L2-normalised)
    chunk_text       FTS5 index of chunk titles and text (kept in sync by triggers)
    chunk_usage      per chunk: how often a search or an assistant surfaced it, and when last (the knowledge
                     map shows what was never retrieved, so rarely used passages stay discoverable)
    meta             the embedding model and size the library was built with

Every query takes `owner`: an API key id, or None for admin keys (every owner). `where` turns filters into SQL
so they run before any ranking.

Schema versions (`PRAGMA user_version`): a file of version 2 (which also held extracted forms and their
reviews) is upgraded in place on first use (`_UPGRADE_FROM_2`: documents and passages are kept, with their
embeddings and retrieval counts); any other old version is refused with `OutdatedLibrary`.
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

import numpy as np

from library.ingest import ChunkDraft, DocumentDraft
from library.schema import (
    WORKSPACE_PREFIX,
    DocumentDetail,
    DocumentFilters,
    LibraryDocument,
    PageInfo,
    Passage,
    PassageList,
    SearchFilters,
    SourceList,
    SourceSummary,
)

SCHEMA_VERSION = 3  # PRAGMA user_version; 0 = new file

_DOCUMENTS = """(
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    media_type TEXT NOT NULL,
    length_bytes INTEGER NOT NULL,
    location TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    pages TEXT NOT NULL DEFAULT '[]',  -- JSON [{n, width, height}]
    created_at TEXT NOT NULL,
    UNIQUE (owner, content_hash)
)"""
_CHUNKS = """(
    seq INTEGER PRIMARY KEY,  -- stable key for the FTS index
    id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    section_title TEXT NOT NULL,
    header_level INTEGER,
    page_number INTEGER,
    sheet_name TEXT,
    embedding BLOB NOT NULL,
    UNIQUE (document_id, chunk_index)
)"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents {_DOCUMENTS};
CREATE TABLE IF NOT EXISTS document_chunks {_CHUNKS};

CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_text USING fts5(
    section_title, content, content='document_chunks', content_rowid='seq');

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON document_chunks BEGIN
    INSERT INTO chunk_text(rowid, section_title, content) VALUES (new.seq, new.section_title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON document_chunks BEGIN
    INSERT INTO chunk_text(chunk_text, rowid, section_title, content)
    VALUES ('delete', old.seq, old.section_title, old.content);
END;

CREATE TABLE IF NOT EXISTS chunk_usage (
    seq INTEGER PRIMARY KEY REFERENCES document_chunks(seq) ON DELETE CASCADE,
    hits INTEGER NOT NULL DEFAULT 0,
    last_hit TEXT
);
"""

# Version 2 -> 3: the same documents and passages without the form, review, client and tax-year columns. The
# tables are rebuilt under new names and swapped in (SQLite cannot drop indexed or referenced columns); `seq`
# values are kept, so the FTS index and `chunk_usage` stay valid. Runs with foreign keys off, in one transaction;
# `SCHEMA` then recreates the triggers and indexes that went with the old tables.
_UPGRADE_FROM_2 = f"""
BEGIN;
CREATE TABLE documents_v3 {_DOCUMENTS};
INSERT INTO documents_v3 SELECT id, owner, title, type, media_type, length_bytes, location, content_hash, pages,
    created_at FROM documents;
CREATE TABLE document_chunks_v3 {_CHUNKS};
INSERT INTO document_chunks_v3 SELECT seq, id, document_id, chunk_index, content, section_title, header_level,
    page_number, sheet_name, embedding FROM document_chunks;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS forms;
DROP TABLE document_chunks;
DROP TABLE documents;
ALTER TABLE documents_v3 RENAME TO documents;
ALTER TABLE document_chunks_v3 RENAME TO document_chunks;
PRAGMA user_version = {SCHEMA_VERSION};
COMMIT;
"""

MAX_SECTIONS = 12  # section titles listed per source
_WORKSPACE_LIKE = WORKSPACE_PREFIX.replace("_", "\\_") + "%"  # no LIKE wildcards in the prefix today; stay safe
_DOCUMENT_COLUMNS = """
    d.id, d.title, d.type, d.media_type, d.length_bytes, d.location, d.content_hash, d.created_at, d.pages,
    (SELECT count(*) FROM document_chunks c WHERE c.document_id = d.id) AS chunks
"""


class IndexMismatch(RuntimeError):
    """The library was built with another embedding model or size."""


class OutdatedLibrary(RuntimeError):
    """The database file was created by a version of the library that cannot be upgraded."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def where(filters: SearchFilters, owner: str | None) -> tuple[str, list]:
    """SQL conditions over `d` (documents). `owner=None`: every owner (admin keys)."""
    q, origin = getattr(filters, "q", None), getattr(filters, "origin", None)
    like = "%" + (q or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    clauses = [
        ("d.owner = ?", [owner]) if owner is not None else None,
        (f"d.id IN ({','.join('?' * len(filters.document_ids))})", filters.document_ids)
        if filters.document_ids else None,
        ("d.title LIKE ? ESCAPE '\\'", [like]) if q else None,
        ("d.location LIKE ? ESCAPE '\\'", [_WORKSPACE_LIKE]) if origin == "workspace" else None,
        ("d.location NOT LIKE ? ESCAPE '\\'", [_WORKSPACE_LIKE]) if origin == "upload" else None,
    ]
    clauses = [c for c in clauses if c]
    return " AND ".join(sql for sql, _ in clauses) or "1", [p for _, values in clauses for p in values]


def _matching(filters: SearchFilters, owner: str | None) -> tuple[str, list]:
    """Subquery of the ids of the documents matching `filters`."""
    sql, params = where(filters, owner)
    return f"SELECT d.id FROM documents d WHERE {sql}", params


def _document(row: sqlite3.Row) -> LibraryDocument:
    return LibraryDocument(**{k: row[k] for k in row.keys() if k != "pages"},  # noqa: SIM118 (sqlite3.Row)
                           page_count=len(json.loads(row["pages"])))


def index_dimensions(conn: sqlite3.Connection, model_id: str, vectors: np.ndarray | None = None) -> int | None:
    """
    The library's vector size. Records model and size on the first insert;
    afterwards both must match the configured embedder.
    """
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    if not meta and vectors is not None:
        conn.executemany("INSERT INTO meta VALUES (?, ?)",
                         [("embedding_model", model_id), ("dimensions", str(vectors.shape[1]))])
        return vectors.shape[1]
    if not meta:
        return None
    if meta["embedding_model"] != model_id or (vectors is not None and vectors.shape[1] != int(meta["dimensions"])):
        raise IndexMismatch(f"The library was built with embedding model {meta['embedding_model']}; "
                            f"the config uses {model_id}. Switch back, or delete the library database and re-upload.")
    return int(meta["dimensions"])


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._ready = False
        self._lock = threading.Lock()

    # --- connection ----------------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection per operation, committed on success; the schema is created or upgraded on first use."""
        with self._lock:
            if not self._ready:
                self._prepare()
                self._ready = True
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'documents'").fetchone():
                version = 1  # a file from before versions were recorded
            if version == 2:
                conn.executescript(_UPGRADE_FROM_2)  # foreign keys are off on this connection
            elif version not in (0, SCHEMA_VERSION):
                raise OutdatedLibrary(f"{self.path} was created by an older version of the library. Delete it "
                                      "(or set another library.database) and add the documents again.")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        finally:
            conn.close()

    # --- documents -----------------------------------------------------------------------

    def insert(self, draft: DocumentDraft, vectors: np.ndarray, owner: str, model_id: str) -> str:
        """Store a document and its chunks. Returns its id."""
        doc_id = str(uuid.uuid4())
        with self.connect() as conn:
            if draft.chunks:
                index_dimensions(conn, model_id, vectors)
            conn.execute(
                "INSERT INTO documents (id, owner, title, type, media_type, length_bytes, location, content_hash,"
                " pages, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, owner, draft.title, draft.type.value, draft.media_type, draft.length_bytes, draft.location,
                 draft.content_hash, json.dumps([p.model_dump() for p in draft.pages]), now()))
            self._insert_chunks(conn, doc_id, draft.chunks, vectors)
        return doc_id

    @staticmethod
    def _insert_chunks(conn: sqlite3.Connection, doc_id: str, chunks: list[ChunkDraft], vectors: np.ndarray) -> None:
        conn.executemany(
            "INSERT INTO document_chunks (id, document_id, chunk_index, content, section_title, header_level,"
            " page_number, sheet_name, embedding) VALUES (?,?,?,?,?,?,?,?,?)",
            [(str(uuid.uuid4()), doc_id, i, c.content, c.section_title, c.header_level, c.page_number, c.sheet_name,
              vectors[i].astype(np.float32).tobytes()) for i, c in enumerate(chunks)])

    def find(self, owner: str, content_hash: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM documents WHERE owner = ? AND content_hash = ?",
                               (owner, content_hash)).fetchone()
        return row["id"] if row else None

    def document(self, document_id: str, owner: str | None) -> DocumentDetail | None:
        sql, params = where(SearchFilters(document_ids=[document_id]), owner)
        with self.connect() as conn:
            row = conn.execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents d WHERE {sql}", params).fetchone()
        if row is None:
            return None
        return DocumentDetail(**_document(row).model_dump(), pages=[PageInfo(**p) for p in json.loads(row["pages"])])

    def list(self, filters: DocumentFilters, owner: str | None, limit: int, offset: int,
             oldest_first: bool = False) -> tuple[int, list[LibraryDocument]]:
        """(total matching, page of documents), newest first unless `oldest_first`."""
        sql, params = where(filters, owner)
        order = "ASC" if oldest_first else "DESC"
        with self.connect() as conn:
            total = conn.execute(f"SELECT count(*) FROM documents d WHERE {sql}", params).fetchone()[0]
            rows = conn.execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents d WHERE {sql}"
                                f" ORDER BY d.created_at {order} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        return total, [_document(r) for r in rows]

    def delete(self, document_id: str, owner: str | None) -> str | None:
        """Delete a document with its chunks. Returns its content hash, None if not found."""
        sql, params = where(SearchFilters(document_ids=[document_id]), owner)
        with self.connect() as conn:
            row = conn.execute(f"SELECT d.content_hash FROM documents d WHERE {sql}", params).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return row["content_hash"]

    def at_location(self, owner: str, location: str) -> list[tuple[str, str]]:
        """(document id, content hash) of the owner's documents stored under `location`, newest first."""
        with self.connect() as conn:
            rows = conn.execute("SELECT id, content_hash FROM documents WHERE owner = ? AND location = ?"
                                " ORDER BY created_at DESC", (owner, location)).fetchall()
        return [(row["id"], row["content_hash"]) for row in rows]

    def hash_in_use(self, content_hash: str) -> bool:
        """True when another document (another owner's upload of the same file) still uses the file."""
        with self.connect() as conn:
            return bool(conn.execute("SELECT 1 FROM documents WHERE content_hash = ?", (content_hash,)).fetchone())

    def media(self, document_id: str, owner: str | None) -> sqlite3.Row | None:
        """(content_hash, media_type, title, type, location, pages) of a document."""
        sql, params = where(SearchFilters(document_ids=[document_id]), owner)
        with self.connect() as conn:
            return conn.execute("SELECT d.content_hash, d.media_type, d.title, d.type, d.location, d.pages"
                                f" FROM documents d WHERE {sql}", params).fetchone()

    # --- the index, browsable ----------------------------------------------------------------

    @staticmethod
    def record_hits(conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
        """Count one retrieval for each chunk (a search hit, or a passage an assistant read)."""
        if not chunk_ids:
            return
        conn.execute(
            "INSERT INTO chunk_usage (seq, hits, last_hit) SELECT seq, 1, ? FROM document_chunks"
            f" WHERE id IN ({','.join('?' * len(chunk_ids))})"
            " ON CONFLICT (seq) DO UPDATE SET hits = hits + 1, last_hit = excluded.last_hit", [now(), *chunk_ids])

    def sources(self, filters: DocumentFilters, owner: str | None, limit: int, offset: int,
                unused_only: bool = False) -> SourceList:
        """The index by source. Totals cover the scope (owner, `document_ids`, `origin`); `q` and `unused_only`
        narrow the page. Sources with never-retrieved passages come first when `unused_only`, else the newest."""
        scope = DocumentFilters(origin=filters.origin).model_copy(update={"document_ids": filters.document_ids})
        scoped, scope_params = _matching(scope, owner)
        matching, params = _matching(filters, owner)
        usage = ("FROM documents d LEFT JOIN document_chunks c ON c.document_id = d.id"
                 " LEFT JOIN chunk_usage u ON u.seq = c.seq")
        per_source = ("SELECT d.id AS document_id, d.title, d.type, d.location, d.created_at,"
                      " count(c.seq) AS passages, count(c.seq) - count(u.seq) AS never_retrieved,"
                      f" max(u.last_hit) AS last_retrieved_at {usage} WHERE d.id IN ({matching}) GROUP BY d.id"
                      + (" HAVING never_retrieved > 0" if unused_only else ""))
        order = "never_retrieved DESC, created_at DESC" if unused_only else "created_at DESC"
        with self.connect() as conn:
            totals = conn.execute(f"SELECT count(DISTINCT d.id), count(c.seq), count(c.seq) - count(u.seq) {usage}"
                                  f" WHERE d.id IN ({scoped})", scope_params).fetchone()
            count = conn.execute(f"SELECT count(*) FROM ({per_source})", params).fetchone()[0]
            rows = conn.execute(f"{per_source} ORDER BY {order} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            sections = self._sections(conn, [r["document_id"] for r in rows])
        return SourceList(sources=totals[0], passages=totals[1], never_retrieved=totals[2], count=count,
                          items=[SourceSummary(**dict(r), sections=sections.get(r["document_id"], [])) for r in rows])

    @staticmethod
    def _sections(conn: sqlite3.Connection, document_ids: list[str]) -> dict[str, list[str]]:
        """document id -> its distinct section titles in document order, at most `MAX_SECTIONS`."""
        if not document_ids:
            return {}
        rows = conn.execute(
            "SELECT document_id, section_title FROM document_chunks WHERE section_title != ''"
            f" AND document_id IN ({','.join('?' * len(document_ids))}) GROUP BY document_id, section_title"
            " ORDER BY document_id, min(chunk_index)", document_ids)
        found: dict[str, list[str]] = {}
        for document_id, title in rows:
            titles = found.setdefault(document_id, [])
            if len(titles) < MAX_SECTIONS:
                titles.append(title)
        return found

    def passages(self, document_id: str, owner: str | None, limit: int, offset: int,
                 record: bool = False) -> PassageList | None:
        """A document's passages in order, in full; None when the owner may not read it. `record`: count the
        returned passages as retrieved (an assistant read them)."""
        sql, params = where(SearchFilters(document_ids=[document_id]), owner)
        with self.connect() as conn:
            document = conn.execute("SELECT d.title, (SELECT count(*) FROM document_chunks c"
                                    f" WHERE c.document_id = d.id) AS count FROM documents d WHERE {sql}",
                                    params).fetchone()
            if document is None:
                return None
            rows = conn.execute(
                'SELECT c.id AS chunk_id, c.chunk_index AS "index", c.section_title, c.page_number, c.sheet_name,'
                " c.content, coalesce(u.hits, 0) AS retrievals, u.last_hit AS last_retrieved_at"
                " FROM document_chunks c LEFT JOIN chunk_usage u ON u.seq = c.seq WHERE c.document_id = ?"
                " ORDER BY c.chunk_index LIMIT ? OFFSET ?", (document_id, limit, offset)).fetchall()
            if record:
                self.record_hits(conn, [r["chunk_id"] for r in rows])
        return PassageList(document_id=document_id, title=document["title"], count=document["count"],
                           passages=[Passage(**dict(r)) for r in rows])
