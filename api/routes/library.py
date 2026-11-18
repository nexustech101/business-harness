"""Document library: upload, list, read, delete, render and search documents.

Each API key sees the documents it uploaded; admin keys see all of them.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile

from api.deps import (
    MB,
    ClientDep,
    LibraryDep,
    ParserDep,
    RateLimit,
    SettingsDep,
    job_slot,
    owner_scope,
    read_upload,
    require_api_key,
)
from api.errors import responses
from core.schema import Envelope
from library.files import MAX_WIDTH
from library.ingest import read_file
from library.schema import (
    WORKSPACE_PREFIX,
    DocumentDetail,
    DocumentFilters,
    DocumentList,
    Origin,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/v1/library", tags=["Library"], dependencies=[Depends(require_api_key)],
                   responses=responses(401, 429))


@router.post(
    "/documents",
    response_model=Envelope[DocumentDetail],
    status_code=201,
    responses=responses(400, 409, 413, 415, 422, 503),
    dependencies=[Depends(RateLimit("library")), Depends(job_slot)],
    summary="Add a document to the library",
)
async def add_document(
    response: Response,
    key: ClientDep,
    library: LibraryDep,
    parser: ParserDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF, image, .txt, .md, .csv or .xlsx")],
    title: Annotated[str | None, Form(max_length=500, description="Default: the file name.")] = None,
    location: Annotated[str | None, Form(max_length=1000, description="Where the original is kept.")] = None,
) -> Envelope[DocumentDetail]:
    """
    Store a file: the original (for page rendering and download) and its
    searchable passages. PDFs and images are read page by page (OCR where
    there is no text layer); text files by section, paragraph or row. SSNs
    are masked in the passages. The same file uploaded again returns the
    stored document with 200 instead of 201.
    """
    filename = file.filename or "upload"
    if (location or filename).startswith(WORKSPACE_PREFIX):  # the location defaults to the file name
        raise HTTPException(400, f"A location or file name may not start with {WORKSPACE_PREFIX} "
                                 "(the workspace's own records).")
    data = await read_upload(file, settings.max_upload_mb * MB)
    owner = str(key.id)
    existing = library.find(owner, hashlib.sha256(data).hexdigest())
    if existing is None:
        draft = await read_file(parser, data, filename, chunk_chars=library.config.chunk_chars, title=title,
                                location=location)
        existing, created = await library.add(draft, owner, data)
    else:
        created = False
    response.status_code = 201 if created else 200
    return Envelope(data=existing)


@router.get("/documents", response_model=Envelope[DocumentList])
def list_documents(
    key: ClientDep,
    library: LibraryDep,
    q: Annotated[str | None, Query(max_length=200, description="Text in the title.")] = None,
    origin: Annotated[Origin | None, Query(
        description="upload: uploaded files (default); workspace: the workspace's own index records "
                    "(profile, discovery answers, notes).")] = "upload",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Annotated[Literal["newest", "oldest"], Query(description="By upload time.")] = "newest",
) -> Envelope[DocumentList]:
    """`count` is the total matching the filters."""
    filters = DocumentFilters(q=q, origin=origin)
    total, documents = library.list(filters, owner_scope(key), limit, offset, oldest_first=order == "oldest")
    return Envelope(data=DocumentList(count=total, documents=documents))


@router.get("/documents/{document_id}", response_model=Envelope[DocumentDetail], responses=responses(404))
def get_document(document_id: str, key: ClientDep, library: LibraryDep) -> Envelope[DocumentDetail]:
    """Metadata and page sizes."""
    document = library.get(document_id, owner_scope(key))
    if document is None:
        raise HTTPException(404, "Document not found.")
    return Envelope(data=document)


@router.delete("/documents/{document_id}", status_code=204, responses=responses(404))
def delete_document(document_id: str, key: ClientDep, library: LibraryDep) -> None:
    """Removes the document, its passages and the original file."""
    if not library.delete(document_id, owner_scope(key)):
        raise HTTPException(404, "Document not found.")


@router.get(
    "/documents/{document_id}/pages/{page}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "The page as PNG"},
               304: {"description": "Not modified"}, **responses(404)},
    summary="Render one page as PNG",
)
def page_image(
    document_id: str, page: int, request: Request, key: ClientDep, library: LibraryDep,
    width: Annotated[int, Query(ge=100, le=MAX_WIDTH, description="Image width in pixels.")] = 1200,
) -> Response:
    """PDFs are rendered at `width` pixels; images are scaled to it. Cached by ETag (file hash, page, width)."""
    rendered = library.page_png(document_id, page, width, owner_scope(key))
    if rendered is None:
        raise HTTPException(404, "Page not found.")
    png, etag = rendered
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(png, media_type="image/png", headers=headers)


@router.get(
    "/documents/{document_id}/file",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The uploaded file"},
               **responses(404)},
    summary="Download the original file",
)
def original_file(document_id: str, key: ClientDep, library: LibraryDep) -> Response:
    original = library.original(document_id, owner_scope(key))
    if original is None:
        raise HTTPException(404, "Document not found.")
    data, media_type, name = original
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_. ") or "document"
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.post(
    "/search",
    response_model=Envelope[SearchResponse],
    responses=responses(409, 503),
    dependencies=[Depends(RateLimit("search"))],
    summary="Search the library",
)
async def search(body: SearchRequest, key: ClientDep, library: LibraryDep) -> Envelope[SearchResponse]:
    """
    The same search the assistants run: filters first (in the database), then
    ranking by meaning and by keywords. `similarity` is the cosine similarity
    to the query (null when a hit matched on keywords only).
    """
    hits = await library.search(body.query, body.filters, owner_scope(key), body.limit)
    return Envelope(data=SearchResponse(hits=hits))
