"""System routes: health (no auth) and key check."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import ClientDep, ParserDep
from core.schema import ApiKeyInfo, Envelope, HealthResponse

router = APIRouter(tags=["System"])


@router.get("/health", response_model=Envelope[HealthResponse])
def health(parser: ParserDep) -> Envelope[HealthResponse]:
    """`ok` once the document parser (Docling) is loaded; `degraded` until then."""
    return Envelope(data=HealthResponse(status="ok" if parser.loaded else "degraded", docling_loaded=parser.loaded))


@router.get("/auth/me", response_model=Envelope[ApiKeyInfo])
def current_client(client: ClientDep) -> Envelope[ApiKeyInfo]:
    """Verify a key without doing any work."""
    return Envelope(data=ApiKeyInfo(**client.model_dump(exclude={"key_hash"})))
