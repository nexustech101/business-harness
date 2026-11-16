"""The knowledge index: everything the workspace can search (uploaded documents and its own records: business
profile, discovery answers, notes), browsable source by source so nothing depends on being found by a search.

Every route works in the calling key's own workspace (`api.deps.business_owner`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import BusinessDep, ClientDep, RateLimit, business_owner, require_api_key
from api.errors import responses
from business.schema import KnowledgeMap, KnowledgeSearchRequest, KnowledgeSearchResponse
from core.schema import Envelope
from library.schema import DocumentFilters, Origin, PassageList

router = APIRouter(prefix="/v1/knowledge", tags=["Knowledge"], dependencies=[Depends(require_api_key)],
                   responses=responses(401))


@router.get("", response_model=Envelope[KnowledgeMap])
async def knowledge_map(
    key: ClientDep, business: BusinessDep,
    q: Annotated[str | None, Query(max_length=200, description="Text in the source's title.")] = None,
    origin: Annotated[Origin | None, Query(description="upload: files; workspace: the workspace's records.")] = None,
    unused: Annotated[bool, Query(description="Only sources with passages never retrieved, most first.")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[KnowledgeMap]:
    """
    Every source in the index with its sections, passage count and how many passages no search or assistant has
    surfaced yet. The totals cover the whole index (within `origin`); `q` and `unused` narrow `items`. The
    workspace's records are brought up to date first.
    """
    filters = DocumentFilters(q=q, origin=origin)
    return Envelope(data=await business.knowledge(business_owner(key), filters, limit, offset, unused))


@router.get("/{document_id}/passages", response_model=Envelope[PassageList], responses=responses(404))
def passages(document_id: str, key: ClientDep, business: BusinessDep,
             limit: Annotated[int, Query(ge=1, le=100)] = 20,
             offset: Annotated[int, Query(ge=0)] = 0) -> Envelope[PassageList]:
    """A source's passages in document order, exactly as indexed, with how often each was retrieved."""
    found = business.passages(business_owner(key), document_id, limit, offset)
    if found is None:
        raise HTTPException(404, "Source not found.")
    return Envelope(data=found)


@router.post("/search", response_model=Envelope[KnowledgeSearchResponse], responses=responses(409, 429, 503),
             dependencies=[Depends(RateLimit("search"))])
async def search(body: KnowledgeSearchRequest, key: ClientDep,
                 business: BusinessDep) -> Envelope[KnowledgeSearchResponse]:
    """
    Search files and workspace records together (meaning and keywords, as `POST /v1/library/search`). One source
    fills at most half of `hits`; `other_sources` names the sources that matched without a passage among them.
    """
    return Envelope(data=await business.search(business_owner(key), body))
