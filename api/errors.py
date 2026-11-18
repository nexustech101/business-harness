"""errors.py

Every error leaves the API as

    {"error": {"code", "message", "request_id", "details"}}

with a matching HTTP status. Domain exceptions map to a status and code in
`DOMAIN_ERRORS` (status, code, details, and per error a fixed message, a
`Retry-After` and a log line); nothing in `core` knows about HTTP.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, NamedTuple

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent.agent import ChatUnavailable
from business.connectors import ConnectorError, InvalidConnector, NotAllowed
from business.database import DatabaseError
from business.errors import AlreadyDecided, InvalidSpec, NotActive, OutdatedWorkspace
from core.jobs import Busy
from core.parser import SUPPORTED_MEDIA_TYPES, ConversionFailed, DocumentTooLarge, UnsupportedDocument
from core.schema import ErrorResponse
from library.search import EmbeddingsUnavailable
from library.store import IndexMismatch, OutdatedLibrary

log = logging.getLogger("business_partner")

HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 503: "busy",
              413: "payload_too_large", 429: "rate_limited"}


class DomainError(NamedTuple):
    status: int
    code: str
    details: Callable[[Any], dict | None] = lambda e: None
    message: str | None = None  # public message instead of str(exc)
    retry_after: int | None = None  # seconds, as the Retry-After header
    log: str | None = None  # logged at ERROR with the exception text


_MODEL_DOWN = DomainError(503, "model_unavailable", message="A model backend is unavailable. Try again shortly.",
                          retry_after=10, log="model backend unavailable")

DOMAIN_ERRORS: dict[type[Exception], DomainError] = {
    UnsupportedDocument: DomainError(415, "unsupported_media_type", lambda e: {"supported": SUPPORTED_MEDIA_TYPES}),
    DocumentTooLarge: DomainError(413, "too_many_pages"),
    ConversionFailed: DomainError(422, "unreadable_document"),
    EmbeddingsUnavailable: _MODEL_DOWN,
    ChatUnavailable: _MODEL_DOWN,
    IndexMismatch: DomainError(409, "index_mismatch"),
    InvalidSpec: DomainError(422, "invalid_assistant"),
    NotActive: DomainError(409, "assistant_inactive"),
    AlreadyDecided: DomainError(409, "already_decided"),
    InvalidConnector: DomainError(422, "invalid_connector"),
    DatabaseError: DomainError(422, "invalid_database_request"),
    NotAllowed: DomainError(403, "forbidden"),
    ConnectorError: DomainError(502, "connector_failed"),
    Busy: DomainError(503, "busy", retry_after=30),
    OutdatedLibrary: DomainError(500, "outdated_library", log="outdated library database"),
    OutdatedWorkspace: DomainError(500, "outdated_workspace", log="outdated workspace database"),
}

DESCRIPTIONS = {
    400: "Empty or malformed request",
    401: "Missing or invalid API key",
    404: "Not found",
    409: "Conflict: library built with another embedding model, an inactive assistant or an approval already "
         "decided",
    403: "Admin key required",
    413: "File or page count over the limit",
    415: "Not a supported file type",
    422: "Unreadable document; invalid request, assistant spec, connector or database statement",
    429: "Rate limit exceeded",
    502: "A connector (MCP server) could not be reached or failed",
    503: "Server busy, or a model backend is unavailable",
}


def responses(*codes: int) -> dict[int, dict]:
    """OpenAPI `responses=` entries for the given status codes."""
    return {c: {"model": ErrorResponse, "description": DESCRIPTIONS[c]} for c in codes}


def error_response(request: Request, status: int, code: str, message: str, details: dict | None = None,
                   headers: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message,
                      "request_id": getattr(request.state, "request_id", None), "details": details}}
    return JSONResponse(status_code=status, content=body, headers=headers)


def register(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return error_response(request, exc.status_code, HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail),
                              headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return error_response(request, 422, "invalid_request", "Request validation failed.", {"errors": errors})

    async def domain_error(request: Request, exc: Exception):
        error = DOMAIN_ERRORS[type(exc)]
        if error.log:
            log.error(error.log, extra={"ctx": {"error": str(exc)}})
        return error_response(request, error.status, error.code, error.message or str(exc), error.details(exc),
                              headers={"Retry-After": str(error.retry_after)} if error.retry_after else None)

    for exc_type in DOMAIN_ERRORS:
        app.add_exception_handler(exc_type, domain_error)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"ctx": {"request_id": getattr(request.state, "request_id", None)}})
        return error_response(request, 500, "internal_error", "Internal server error.")
