"""app.py

Builds the FastAPI application: lifespan (database, model loading), request
middleware, error handlers and routers. Routes live in `api/routes/`.

    GET  /health                      readiness (no auth)
    GET  /auth/me                     check a key
    POST|GET|DELETE /api-keys         key management (admin)
    POST|GET|DELETE /v1/library/documents[/{id}]   stored documents and their originals
    GET  /v1/library/documents/{id}/pages/{n} | /file   page PNG, original file
    POST /v1/library/search           filtered semantic + keyword search
    POST /v1/assistant/chat           questions answered from the library, with read-only tools
    GET  /v1/workspace, POST /v1/workspace/hints     workspace summary, contextual hints
    GET|PUT /v1/business/profile, GET /v1/business/interview, POST .../interview/answers   profile, interview
    POST /v1/partner/chat             the business partner (interview, organize, recommend, draft assistants)
    GET|PUT /v1/business/documents[/{id}], GET|POST /v1/business/notes   organized documents, notes board
    /v1/assistants[...]               assistant specs, status, context preview, runs
    GET /v1/approvals, POST /v1/approvals/{id}/decision   the approvals queue
    /v1/connectors[...]               connector store (MCP servers and built-in apps), installs, tools, OAuth
    /v1/databases/{id}[...]           tables, rows and SQL of a workspace database (a built-in connector)
    GET /v1/knowledge, GET .../{id}/passages, POST .../search   the whole index, browsable and searchable
    GET  /*                           the dashboard (web/dist), when built

*Usage:*
>>> app = create_app()                      # uvicorn main:app
>>> app = create_app(settings, parser=fake, load_models=False, business=business)   # tests
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

import agent
from agent.agent import Assistant
from agent.config import load_config
from api import errors
from api.deps import MB, BodyLimit, RateWindows
from api.routes import assistant as assistant_routes
from api.routes import assistants as assistants_routes
from api.routes import business as business_routes
from api.routes import connectors as connectors_routes
from api.routes import databases as databases_routes
from api.routes import keys, system
from api.routes import knowledge as knowledge_routes
from api.routes import library as library_routes
from api.web import mount_dashboard
from business.config import load_business_config
from business.connectors import ConnectorHub
from business.service import Business
from core.config import PROJECT_ROOT, Settings, get_settings
from core.db import db, init_db
from core.jobs import JobGate
from core.parser import DoclingParser
from core.utils import setup_logging
from library.service import Library

log = logging.getLogger("business_partner")

WEB_DIST = PROJECT_ROOT / "web" / "dist"

DISCLAIMER = (
    "Answers and actions come from language models working on your documents: decision support, not legal, "
    "tax or financial advice. Check them against the source before relying on them. See DISCLAIMER.md."
)


def create_app(
    settings: Settings | None = None,
    parser: DoclingParser | None = None,
    load_models: bool = True,
    dispose_db_on_shutdown: bool = True,
    assistant: tuple[Library, Assistant] | None = None,
    web_dist: Path | None = WEB_DIST,
    business: Business | None = None,
) -> FastAPI:
    """
    `assistant`: (library, assistant) to use instead of building them from
    `settings.assistant_config`. `business`: the workspace (its `hub` serves the
    connector routes) instead of building both from the same file's
    `business` section (the workspace shares the library and the chat model). `web_dist`: the
    built dashboard, served at `/` when it has an `index.html` (otherwise `/`
    redirects to `/docs`).
    """
    settings = settings or get_settings()
    parser = parser or DoclingParser(settings)
    library, assistant_ = assistant or agent.build(load_config(settings.assistant_config))
    if business is None:
        config = load_business_config(settings.assistant_config)
        # No secrets key in the environment: the hub generates one in `key_file` the first time it stores a token.
        hub = ConnectorHub(config.database, config.secrets_key(), config.public_url, key_file=config.key_file)
        business = Business(config, library, assistant_.chat, hub)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level, settings.log_json)
        init_db()
        if load_models:  # Docling weights load once per process and stay resident
            await run_in_threadpool(parser.load)
        log.info("api ready")
        yield
        if dispose_db_on_shutdown:  # terminal: registers managers can't be reused afterwards
            db.dispose_all()

    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        lifespan=lifespan,
        description="A business workspace: a partner that learns the business from the owner and its documents, "
                    "a searchable knowledge index, role assistants, and connectors they act through.\n\n"
                    + DISCLAIMER,
    )
    app.state.settings = settings
    app.state.parser = parser
    app.state.rate_windows = RateWindows()
    app.state.jobs = JobGate(settings.max_concurrent_jobs, settings.max_queued_jobs)
    app.state.library = library
    app.state.assistant = assistant_
    app.state.business = business
    app.state.connectors = business.hub
    app.add_middleware(BodyLimit, settings=settings)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started = time.perf_counter()
        # Early refusal when the client declares an oversized body; BodyLimit enforces the actual bytes.
        limit_mb = settings.max_upload_mb
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > limit_mb * MB + 64 * 1024:
            response = errors.error_response(
                request, 413, "payload_too_large",
                f"Request exceeds the {limit_mb} MB limit."
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        log.info("request", extra={"ctx": {
            "request_id": request.state.request_id, "method": request.method, "path": request.url.path,
            "status": response.status_code, "ms": int((time.perf_counter() - started) * 1000),
            "client_key": (request.headers.get("X-API-Key") or "")[:11] or None,
        }})
        return response

    errors.register(app)
    app.include_router(system.router)
    app.include_router(keys.router)
    app.include_router(library_routes.router)
    app.include_router(assistant_routes.router)
    app.include_router(business_routes.router)
    app.include_router(assistants_routes.router)
    app.include_router(connectors_routes.router)
    app.include_router(databases_routes.router)
    app.include_router(knowledge_routes.router)

    if web_dist is not None and (web_dist / "index.html").is_file():
        mount_dashboard(app, web_dist)  # last: only paths no API route matched
    else:
        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return app
