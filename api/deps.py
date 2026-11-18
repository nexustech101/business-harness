"""deps.py

FastAPI dependencies and limits: API-key auth, the shared document parser,
library, assistant and settings, per-key rate limits, the upload job slot,
request body size and bounded upload reading.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, UploadFile
from fastapi.security import APIKeyHeader

from agent.agent import Assistant
from business.connectors import ConnectorHub
from business.service import Business
from core.auth import find_active_key, hash_key
from core.config import Settings
from core.models import ApiKey
from core.parser import DoclingParser
from library.service import Library

MB = 1024 * 1024

# --- Auth -------------------------------------------------------------------

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Security(api_key_header)) -> ApiKey:
    record = find_active_key(api_key) if api_key else None
    if record is None:
        raise HTTPException(401, "Missing or invalid API key.", headers={"WWW-Authenticate": "APIKey"})
    return record


def require_admin(key: Annotated[ApiKey, Depends(require_api_key)]) -> ApiKey:
    if not key.is_admin:
        raise HTTPException(403, "Admin key required.")
    return key


ClientDep = Annotated[ApiKey, Depends(require_api_key)]
AdminDep = Annotated[ApiKey, Depends(require_admin)]

# --- App state ----------------------------------------------------------------


def get_parser(request: Request) -> DoclingParser:
    return request.app.state.parser


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_library(request: Request) -> Library:
    return request.app.state.library


def get_assistant(request: Request) -> Assistant:
    return request.app.state.assistant


def get_business(request: Request) -> Business:
    return request.app.state.business


def get_connectors(request: Request) -> ConnectorHub:
    return request.app.state.connectors


def business_owner(key: ApiKey) -> str:
    """Whose business workspace a key works in: its own, admin keys included (a workspace is never shared)."""
    return str(key.id)


def owner_scope(key: ApiKey) -> str | None:
    """Library documents a key may read: its own, or every key's for admin keys (None)."""
    return None if key.is_admin else str(key.id)


ParserDep = Annotated[DoclingParser, Depends(get_parser)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
LibraryDep = Annotated[Library, Depends(get_library)]
AssistantDep = Annotated[Assistant, Depends(get_assistant)]
BusinessDep = Annotated[Business, Depends(get_business)]
ConnectorsDep = Annotated[ConnectorHub, Depends(get_connectors)]

# --- Rate limits -------------------------------------------------------------


class RateWindows:
    """Sliding windows of recent request times per (scope, client). In-process: one per app."""

    def __init__(self) -> None:
        self.times: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def hit(self, scope: str, client: str, calls: int, seconds: int) -> None:
        with self.lock:
            times = self.times[(scope, client)]
            now = time.monotonic()
            while times and now - times[0] >= seconds:
                times.popleft()
            if len(times) >= calls:
                raise HTTPException(
                    429, "Rate limit exceeded.",
                    headers={"Retry-After": str(math.ceil(seconds - (now - times[0])))}
                )
            times.append(now)
            if len(self.times) > 10_000:  # drop idle clients so the map stays bounded
                for key in [k for k, t in self.times.items() if not t or now - t[-1] >= seconds]:
                    del self.times[key]


class RateLimit:
    """
    Dependency limiting requests per API key (or peer address) per scope.
    Limits come from `<scope>_rate_calls` / `<scope>_rate_seconds` in settings
    unless given explicitly.

    *Usage:*
    >>> @router.post("/x", dependencies=[Depends(RateLimit("library"))])
    """

    def __init__(self, scope: str, calls: int | None = None, seconds: int | None = None):
        self.scope, self.calls, self.seconds = scope, calls, seconds

    def __call__(self, request: Request) -> None:
        settings: Settings = request.app.state.settings
        calls = self.calls or getattr(settings, f"{self.scope}_rate_calls")
        seconds = self.seconds or getattr(settings, f"{self.scope}_rate_seconds")
        raw_key = request.headers.get("X-API-Key")
        client = hash_key(raw_key) if raw_key else (request.client.host if request.client else "local")
        request.app.state.rate_windows.hit(self.scope, client, calls, seconds)

# --- Upload jobs (core.jobs.JobGate) -----------------------------------------------


async def job_slot(request: Request) -> AsyncIterator[None]:
    """Dependency: hold an upload slot for the rest of the request (the file is read inside it)."""
    async with request.app.state.jobs.slot():
        yield


# --- Request body ----------------------------------------------------------------


class BodyLimit:
    """
    ASGI middleware counting request body bytes as they arrive, so the limit
    holds without (or despite) a Content-Length header: `max_upload_mb`
    plus room for multipart headers. Raises 413 from inside the body read.
    """

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    @property
    def limit(self) -> int:
        return self.settings.max_upload_mb * MB + 64 * 1024

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit, seen = self.limit, 0

        async def counted():
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > limit:
                raise HTTPException(413, f"Request exceeds the {limit // MB} MB limit.")
            return message

        await self.app(scope, counted, send)


# --- Uploads -------------------------------------------------------------------


async def read_upload(file: UploadFile, max_bytes: int, allow_empty: bool = False) -> bytes:
    """Read an upload in chunks, refusing anything over `max_bytes`."""
    chunks, size = [], 0
    while chunk := await file.read(MB):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(413, f"{file.filename or 'File'} exceeds the {max_bytes // MB} MB limit.")
        chunks.append(chunk)
    if not size and not allow_empty:
        raise HTTPException(400, "The uploaded file is empty.")
    return b"".join(chunks)
