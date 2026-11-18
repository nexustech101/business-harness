"""The library store: documents, originals and pages, the upgrade of an older file, and the document routes."""

from __future__ import annotations

import io
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import agent
from library.files import page_sizes, render_png
from library.schema import DocumentFilters
from library.search import Embedder
from library.service import Library
from library.store import SCHEMA_VERSION, OutdatedLibrary
from tests.conftest import make_test_app
from tests.fakes import Embeddings, add, blank_pdf, config, draft, fake_parser, fake_vector, search


@pytest.fixture
def library(tmp_path):
    return Library(config(tmp_path).library, Embedder(config(tmp_path).embeddings, Embeddings()))


def test_documents_are_listed_newest_first_and_filtered_by_title(library):
    add(library, draft("warehouse lease", title="lease"))
    add(library, draft("price list", title="prices"))
    total, documents = library.list(DocumentFilters(), "1")
    assert (total, [d.title for d in documents]) == (2, ["prices", "lease"])
    assert [d.title for d in library.list(DocumentFilters(), "1", oldest_first=True)[1]] == ["lease", "prices"]
    assert [d.title for d in library.list(DocumentFilters(q="LEA"), "1")[1]] == ["lease"]
    assert library.list(DocumentFilters(q="100%"), "1")[0] == 0  # LIKE wildcards in the text are literal
    assert (documents[0].chunks, documents[0].page_count, documents[0].type) == (1, 0, "txt")


def test_delete_removes_the_file_once_no_document_uses_it(library):
    first = add(library, draft("shared text", title="a", owner_hash="a" * 64), owner="1", data=b"same bytes")
    second = add(library, draft("shared text", title="a", owner_hash="a" * 64), owner="2", data=b"same bytes")
    assert library.original(first.id, "1") == (b"same bytes", "text/plain", "a.txt")
    assert library.delete(first.id, "1") and library.files.load("a" * 64) == b"same bytes"  # still used by owner 2
    assert library.delete(second.id, "2") and library.files.load("a" * 64) is None


def test_images_render_upright_at_the_requested_width():
    out = io.BytesIO()
    Image.new("RGB", (400, 200), "white").save(out, format="PNG")
    assert [(p.width, p.height) for p in page_sizes(out.getvalue(), "image/png")] == [(400, 200)]
    png = render_png(out.getvalue(), "image/png", 1, 800)
    assert Image.open(io.BytesIO(png)).size == (800, 400)
    assert render_png(out.getvalue(), "image/png", 2, 800) is None


# --- upgrading an older library file ---------------------------------------------------------------------

V2 = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, type TEXT NOT NULL,
    media_type TEXT NOT NULL, length_bytes INTEGER NOT NULL, location TEXT NOT NULL, content_hash TEXT NOT NULL,
    client TEXT, tax_year INTEGER, pages TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
    UNIQUE (owner, content_hash));
CREATE TABLE forms (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL, status TEXT NOT NULL, fields TEXT);
CREATE TABLE reviews (form_id TEXT NOT NULL REFERENCES forms(id) ON DELETE CASCADE, field TEXT NOT NULL,
    decision TEXT NOT NULL, PRIMARY KEY (form_id, field));
CREATE TABLE document_chunks (seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    form_id TEXT REFERENCES forms(id) ON DELETE CASCADE, chunk_index INTEGER NOT NULL, content TEXT NOT NULL,
    section_title TEXT NOT NULL, header_level INTEGER, page_number INTEGER, sheet_name TEXT,
    document_type TEXT NOT NULL, tax_year INTEGER, embedding BLOB NOT NULL, UNIQUE (document_id, chunk_index));
CREATE INDEX idx_documents_owner_client ON documents(owner, client COLLATE NOCASE, tax_year);
CREATE INDEX idx_chunks_type_year ON document_chunks(document_type, tax_year);
CREATE VIRTUAL TABLE chunk_text USING fts5(section_title, content, content='document_chunks', content_rowid='seq');
CREATE TRIGGER chunks_ai AFTER INSERT ON document_chunks BEGIN
    INSERT INTO chunk_text(rowid, section_title, content) VALUES (new.seq, new.section_title, new.content);
END;
CREATE TABLE chunk_usage (seq INTEGER PRIMARY KEY REFERENCES document_chunks(seq) ON DELETE CASCADE,
    hits INTEGER NOT NULL DEFAULT 0, last_hit TEXT);
PRAGMA user_version = 2;
"""


def vector(text: str) -> bytes:
    v = np.asarray(fake_vector(text), dtype=np.float32)
    return (v / np.linalg.norm(v)).tobytes()


def test_a_version_2_library_is_upgraded_in_place_keeping_documents_passages_and_usage(library):
    path = library.config.database
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(V2)
        conn.executemany("INSERT INTO meta VALUES (?, ?)", [("embedding_model", library.embedder.model_id),
                                                             ("dimensions", "64")])
        conn.execute("INSERT INTO documents VALUES ('d1', '1', 'handbook', 'md', 'text/markdown', 10, 'handbook.md',"
                     " ?, 'Okafor', 2025, '[]', '2026-01-01T00:00:00+00:00')", ("b" * 64,))
        conn.execute("INSERT INTO forms VALUES ('f1', 'd1', 0, 'ok', '{}')")
        conn.execute("INSERT INTO reviews VALUES ('f1', 'wages', 'confirmed')")
        for seq, (form, text) in enumerate([(None, "refund policy within 24 hours"), ("f1", "wages: 68412.55")], 7):
            conn.execute("INSERT INTO document_chunks VALUES (?, ?, 'd1', ?, ?, ?, 'Policies', NULL, NULL, NULL,"
                         " 'text', 2025, ?)", (seq, f"c{seq}", form, seq - 7, text, vector(text)))
        conn.execute("INSERT INTO chunk_usage VALUES (7, 3, '2026-01-02T00:00:00+00:00')")

    (document,) = library.list(DocumentFilters(), "1")[1]  # first use: upgraded
    assert (document.id, document.title, document.chunks) == ("d1", "handbook", 2)
    assert search(library, "refund policy")[0].content == "refund policy within 24 hours"
    assert search(library, "68412.55")[0].content == "wages: 68412.55"  # the keyword index still works
    passages = library.passages("d1", "1").passages
    assert [(p.index, p.retrievals) for p in passages] == [(0, 5), (1, 2)]  # 3 kept, plus the two searches above
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert not {"forms", "reviews", "documents_v3"} & tables and not {"client", "tax_year"} & columns
    add(library, draft("new upload after the upgrade", title="new"))
    assert library.delete("d1", "1") and all(h.document_id != "d1" for h in search(library, "refund policy"))


def test_an_older_library_file_is_refused(library):
    path = library.config.database
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")  # before versions were recorded
    with pytest.raises(OutdatedLibrary):
        library.list(DocumentFilters(), "1")


# --- HTTP ---------------------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    built = agent.build(config(tmp_path), None, Embeddings())
    app, admin = make_test_app(parser=fake_parser("price list page"), assistant=built)
    with TestClient(app) as client:
        keys = [client.post("/api-keys", json={"name": n}, headers={"X-API-Key": admin}).json()["data"]["key"]
                for n in ("owner", "other")]
        yield SimpleNamespace(client=client, key={"X-API-Key": keys[0]}, other={"X-API-Key": keys[1]},
                              admin={"X-API-Key": admin})


def test_document_pages_and_file_routes(api):
    pdf = blank_pdf(1)
    r = api.client.post("/v1/library/documents", files={"file": ("prices.pdf", pdf, "application/pdf")},
                        data={"title": "Price list"}, headers=api.key)
    assert r.status_code == 201, r.text
    doc = r.json()["data"]
    assert (doc["title"], doc["type"], doc["chunks"], doc["page_count"]) == ("Price list", "pdf", 1, 1)
    assert doc["pages"] == [{"n": 1, "width": 612.0, "height": 792.0}] and doc["location"] == "prices.pdf"

    r = api.client.get(f"/v1/library/documents/{doc['id']}/pages/1", params={"width": 600}, headers=api.key)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).width == 600
    etag = r.headers["etag"]
    assert etag == f'"{doc["content_hash"]}-1-600"'
    cached = api.client.get(f"/v1/library/documents/{doc['id']}/pages/1", params={"width": 600},
                            headers={**api.key, "If-None-Match": etag})
    assert cached.status_code == 304
    assert api.client.get(f"/v1/library/documents/{doc['id']}/pages/2", headers=api.key).status_code == 404
    assert api.client.get(f"/v1/library/documents/{doc['id']}/pages/1", params={"width": 9000},
                          headers=api.key).status_code == 422
    r = api.client.get(f"/v1/library/documents/{doc['id']}/file", headers=api.key)
    assert r.content == pdf and 'filename="Price list.pdf"' in r.headers["content-disposition"]

    for path in ("", "/pages/1", "/file"):  # another key: as if it did not exist
        r = api.client.get(f"/v1/library/documents/{doc['id']}{path}", headers=api.other)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert api.client.get(f"/v1/library/documents/{doc['id']}/pages/1", headers=api.admin).status_code == 200
    listed = api.client.get("/v1/library/documents", headers=api.key).json()["data"]
    assert (listed["count"], listed["documents"][0]["id"]) == (1, doc["id"])
    assert api.client.get("/v1/library/documents", headers=api.other).json()["data"]["count"] == 0
