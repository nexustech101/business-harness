"""library/service.py

`Library`: what the routes and the assistants call. It ties the store (SQL), the embedder (search vectors) and
the original files together; each method is one use case.

*Usage:*
>>> library = Library(config.library, Embedder(config.embeddings))
>>> document, created = await library.add(draft, owner="7", data=data)
>>> hits = await library.search("payment terms for wholesale", SearchFilters(), owner="7")
"""

from __future__ import annotations

import asyncio
import json

from library.config import LibraryConfig
from library.files import SUFFIXES, Files, render_png
from library.ingest import DocumentDraft
from library.schema import (
    DocumentDetail,
    DocumentFilters,
    LibraryDocument,
    PassageList,
    SearchFilters,
    SearchHit,
    SearchOutcome,
    SourceList,
)
from library.search import Embedder, search_chunks
from library.store import Store


class Library:
    def __init__(self, config: LibraryConfig, embedder: Embedder):
        self.config = config
        self.embedder = embedder
        self.store = Store(config.database)
        self.files = Files(config.files)

    # --- documents -----------------------------------------------------------------------

    async def add(self, draft: DocumentDraft, owner: str, data: bytes) -> tuple[DocumentDetail, bool]:
        """(document, created). The same file uploaded again by the same owner returns the stored one."""
        existing = self.find(owner, draft.content_hash)
        if existing:
            return existing, False
        texts = [f"{c.section_title}\n{c.content}".strip() for c in draft.chunks]
        vectors = await self.embedder.embed(texts, "document")

        def store() -> DocumentDetail:
            self.files.save(draft.content_hash, data)
            doc_id = self.store.insert(draft, vectors, owner, self.embedder.model_id)
            return self.store.document(doc_id, owner)

        return await asyncio.to_thread(store), True

    def find(self, owner: str, content_hash: str) -> DocumentDetail | None:
        doc_id = self.store.find(owner, content_hash)
        return self.store.document(doc_id, owner) if doc_id else None

    def get(self, document_id: str, owner: str | None) -> DocumentDetail | None:
        return self.store.document(document_id, owner)

    def list(self, filters: DocumentFilters, owner: str | None, limit: int = 50, offset: int = 0,
             oldest_first: bool = False) -> tuple[int, list[LibraryDocument]]:
        """(total matching, a page of documents)."""
        return self.store.list(filters, owner, limit, offset, oldest_first)

    def delete(self, document_id: str, owner: str | None) -> bool:
        """Removes the document and its chunks, and the original file once no document uses it."""
        content_hash = self.store.delete(document_id, owner)
        if content_hash is None:
            return False
        if not self.store.hash_in_use(content_hash):
            self.files.delete(content_hash)
        return True

    def at_location(self, owner: str, location: str) -> list[tuple[str, str]]:
        """(document id, content hash) of the owner's documents stored under `location`, newest first."""
        return self.store.at_location(owner, location)

    def original(self, document_id: str, owner: str | None) -> tuple[bytes, str, str] | None:
        """(bytes, media type, file name) of the uploaded file."""
        row = self.store.media(document_id, owner)
        data = self.files.load(row["content_hash"]) if row else None
        if data is None:
            return None
        return data, row["media_type"], row["title"] + SUFFIXES.get(row["media_type"], "")

    def page_png(self, document_id: str, page: int, width: int, owner: str | None) -> tuple[bytes, str] | None:
        """(PNG, ETag) of one page; None when the document or page does not exist. Blocking: run in a thread."""
        row = self.store.media(document_id, owner)
        if row is None or not 1 <= page <= len(json.loads(row["pages"])):
            return None
        data = self.files.load(row["content_hash"])
        png = render_png(data, row["media_type"], page, width) if data is not None else None
        return (png, f'"{row["content_hash"]}-{page}-{width}"') if png is not None else None

    # --- search ----------------------------------------------------------------------------

    async def search(self, query: str, filters: SearchFilters, owner: str | None,
                     limit: int | None = None) -> list[SearchHit]:
        return (await self.search_wide(query, filters, owner, limit)).hits

    async def search_wide(self, query: str, filters: SearchFilters, owner: str | None,
                          limit: int | None = None) -> SearchOutcome:
        """`search` plus the sources that matched without a passage among the hits (library/search.py)."""
        limit = min(limit or self.config.default_results, self.config.max_results)
        vector = (await self.embedder.embed([query], "query"))[0]

        def run() -> SearchOutcome:
            with self.store.connect() as conn:
                return search_chunks(conn, self.embedder.model_id, vector, query, filters, owner, limit)

        return await asyncio.to_thread(run)

    # --- the index, browsable ----------------------------------------------------------------

    def sources(self, filters: DocumentFilters, owner: str | None, limit: int = 50, offset: int = 0,
                unused_only: bool = False) -> SourceList:
        """Every source of the index with its sections and how much of it was ever retrieved."""
        return self.store.sources(filters, owner, limit, offset, unused_only)

    def passages(self, document_id: str, owner: str | None, limit: int = 20, offset: int = 0,
                 record: bool = False) -> PassageList | None:
        """A document's passages in full, in order; `record` counts them as retrieved."""
        return self.store.passages(document_id, owner, limit, offset, record)
