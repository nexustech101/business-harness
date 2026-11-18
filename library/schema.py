"""library/schema.py

Request and response models of the library: documents, search, and the index as it can be browsed (sources
and their passages).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Origin = Literal["upload", "workspace"]
WORKSPACE_PREFIX = "workspace://"  # `location` of records the workspace writes into the index (business/memory.py)


class FileType(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    XLSX = "xlsx"


# --- Documents -------------------------------------------------------------------------------


class PageInfo(BaseModel):
    n: int = Field(description="Page number, from 1.")
    width: float = Field(description="Page width in the source's units (PDF points or image pixels).")
    height: float = Field(description="Page height in the same units.")


class LibraryDocument(BaseModel):
    id: str
    title: str
    type: FileType
    media_type: str
    length_bytes: int
    location: str = Field(description="Where the document came from: the uploaded filename or the caller's `location`.")
    content_hash: str = Field(description="SHA-256 of the file. Uploading the same file again returns this document.")
    created_at: datetime
    chunks: int = Field(description="Indexed passages.")
    page_count: int = Field(description="Pages that can be rendered (0 for text files).")


class DocumentDetail(LibraryDocument):
    pages: list[PageInfo]


class DocumentList(BaseModel):
    count: int = Field(description="Total matching the filters.")
    documents: list[LibraryDocument]


class SearchFilters(BaseModel):
    """What a search or a tool may read. Applied in the database before any ranking."""

    document_ids: list[str] | None = Field(default=None, max_length=100, description="Only these documents.")


class DocumentFilters(SearchFilters):
    q: str | None = Field(default=None, max_length=200, description="Text contained in the title.")
    origin: Origin | None = Field(
        default=None, description="upload: files; workspace: records the workspace keeps in the index; null: both.")


# --- Search ----------------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int | None = Field(default=None, ge=1, description="Default and maximum come from the library config.")


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    section_title: str
    page_number: int | None
    sheet_name: str | None
    content: str
    similarity: float | None = Field(description="Cosine similarity to the query; null for keyword-only matches.")


class SourceRef(BaseModel):
    document_id: str
    title: str


class SearchOutcome(BaseModel):
    hits: list[SearchHit]
    other_sources: list[SourceRef] = Field(
        default_factory=list,
        description="Sources that also matched but have no passage among `hits`, best first: open them to read on.")


class SearchResponse(BaseModel):
    hits: list[SearchHit]


# --- The index, browsable ------------------------------------------------------------------------


class SourceSummary(BaseModel):
    """One document of the index with how much of it has ever been retrieved."""

    document_id: str
    title: str
    type: FileType
    location: str
    created_at: datetime
    passages: int = Field(description="Indexed passages (chunks).")
    never_retrieved: int = Field(description="Passages no search result or assistant read has surfaced yet.")
    last_retrieved_at: datetime | None
    sections: list[str] = Field(description="Its section titles, in document order (the first ones).")


class SourceList(BaseModel):
    sources: int = Field(description="Sources in scope, before `q` and `unused_only`.")
    passages: int
    never_retrieved: int
    count: int = Field(description="Sources matching every filter.")
    items: list[SourceSummary]


class Passage(BaseModel):
    chunk_id: str
    index: int = Field(description="Position in the document (0-based).")
    section_title: str
    page_number: int | None
    sheet_name: str | None
    content: str
    retrievals: int = Field(description="Times a search or an assistant surfaced it.")
    last_retrieved_at: datetime | None


class PassageList(BaseModel):
    document_id: str
    title: str
    count: int = Field(description="Passages in the document.")
    passages: list[Passage]
