"""Model providers replaced by httpx.MockTransport, shared by the library, assistant and tool tests.

The fake embedder hashes words into a vector, so texts sharing words are similar; the fake chat
model replays scripted replies. Requests the code sends are recorded so tests can check each
provider's wire format. `fake_parser` stands in for Docling; `FakeHub` for
`business.connectors.ConnectorHub` (same methods, in-memory connectors per owner, recorded calls);
`workspace` builds a `Business` on it.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pypdfium2 as pdfium

import agent
from agent.config import AssistantConfig, load_config
from business.config import BusinessConfig, load_business_config
from business.connectors import ToolResult
from business.schema import ConnectorCreate, ConnectorInfo, ConnectorListing, ConnectorTool, OAuthStart
from business.service import Business
from core.config import PROJECT_ROOT
from core.layout import Block
from core.parser import ParsedDocument
from library.ingest import ChunkDraft, DocumentDraft
from library.schema import FileType, SearchFilters
from library.service import Library

DIM = 64


def fake_vector(text: str, dim: int = DIM) -> list[float]:
    v = np.zeros(dim)
    for word in re.findall(r"\w+", text.lower()):
        if word not in ("search_query", "search_document"):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1
    return v.tolist()


class Embeddings(httpx.MockTransport):
    def __init__(self):
        self.inputs: list[str] = []

        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.inputs += body["input"]
            return httpx.Response(200, json={"data": [{"index": i, "embedding": fake_vector(t)}
                                                      for i, t in enumerate(body["input"])]})
        super().__init__(handle)


class Chat(httpx.MockTransport):
    """Replays `replies` (provider JSON bodies) in order and records each request body."""

    def __init__(self, replies: list[dict]):
        self.requests: list[dict] = []
        self.paths: list[str] = []
        self.headers: list[httpx.Headers] = []

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(request.content))
            self.paths.append(request.url.path)
            self.headers.append(request.headers)
            return httpx.Response(200, json=replies[len(self.requests) - 1])
        super().__init__(handle)


def openai_tool_call(args: dict, call_id: str = "c1", name: str = "search_documents") -> dict:
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


def openai_answer(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 300, "completion_tokens": 20}}


def openai_turn(text: str | None, *calls: tuple[str, dict]) -> dict:
    """One assistant turn with optional text and several tool calls `(name, arguments)`."""
    return {"choices": [{"message": {"content": text, "tool_calls": [
        {"id": f"t{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        for i, (name, args) in enumerate(calls)]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 1}}


def config(tmp_path: Path, provider: str = "ollama", **chat) -> AssistantConfig:
    raw = load_config(PROJECT_ROOT / "config" / "model_config.yml").model_dump()
    raw["library"].update(database=tmp_path / "library.db", files=tmp_path / "files")
    raw["chat"].update(provider=provider, **chat)
    return AssistantConfig.model_validate(raw)


# --- Library documents ---------------------------------------------------------------------------------


def draft(text: str, *, title="doc", owner_hash=None):
    """A one-passage text document."""
    return DocumentDraft(title=title, type=FileType.TXT, media_type="text/plain", length_bytes=len(text),
                         location=f"{title}.txt",
                         content_hash=owner_hash or hashlib.sha256((title + text).encode()).hexdigest(),
                         chunks=[ChunkDraft(content=text)])


def add(library: Library, d: DocumentDraft, owner: str = "1", data: bytes = b"text"):
    return asyncio.run(library.add(d, owner, data))[0]


def search(library: Library, query: str, owner: str | None = "1", **filters):
    return asyncio.run(library.search(query, SearchFilters(**filters), owner))


def blank_pdf(pages: int) -> bytes:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(612, 792)
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def fake_parser(*page_texts: str):
    """Docling's stand-in: `parse` answers one text line per page of `page_texts`; `calls` lists the file names."""
    calls: list[str] = []
    blocks = [Block(n, 30, 30, 400, 45, text) for n, text in enumerate(page_texts or ("page one",), start=1)]

    async def parse(data: bytes, filename: str) -> ParsedDocument:
        calls.append(filename)
        return ParsedDocument(filename, "application/pdf", "0" * 64, len(blocks), True, blocks)

    return SimpleNamespace(loaded=True, parse=parse, calls=calls)


# --- Business workspace ----------------------------------------------------------------------------------


def listing(listing_id: str, name: str, category: str = "Productivity", capabilities=(), auth="none"):
    return ConnectorListing(id=listing_id, name=name, publisher=name, category=category, description=f"{name} tools",
                            capabilities=list(capabilities), availability="Official", docs_url="https://example.com",
                            transport="streamable_http", url=f"https://{listing_id}.example.com/mcp", auth=auth)


def connector(connector_id: str, name: str, status="connected", listing_id=None, error=None) -> ConnectorInfo:
    return ConnectorInfo(id=connector_id, listing_id=listing_id, name=name, transport="streamable_http",
                         url="https://x.example.com/mcp", command=None, args=[], auth="none", has_secret=False,
                         status=status, error=error, tool_count=0, created_at="2026-01-01T00:00:00Z", checked_at=None)


def connector_tool(connector_id: str, name: str, read_only: bool) -> ConnectorTool:
    return ConnectorTool(connector_id=connector_id, name=name, description=f"{name} tool", read_only=read_only,
                         input_schema={"type": "object", "properties": {"id": {"type": "string"}}})


class FakeHub:
    """`ConnectorHub` in memory. `installed`: owner -> connectors; `tools_`: the tools of every connector;
    `results`: tool name -> ToolResult. `calls` records every `call` as (owner, connector id, tool, arguments)."""

    def __init__(self, catalog=(), installed=None, tools=(), results=None):
        self.listings = list(catalog)
        self.installed: dict[str, dict[str, ConnectorInfo]] = {
            owner: {c.id: c for c in connectors} for owner, connectors in (installed or {}).items()}
        self.tools_ = list(tools)
        self.results = results or {}
        self.calls: list[tuple] = []

    def catalog(self) -> list[ConnectorListing]:
        return self.listings

    def list(self, owner: str) -> list[ConnectorInfo]:
        return list(self.installed.get(owner, {}).values())

    def get(self, owner: str, connector_id: str) -> ConnectorInfo | None:
        return self.installed.get(owner, {}).get(connector_id)

    async def add(self, owner: str, request: ConnectorCreate, admin: bool) -> ConnectorInfo:
        info = connector(f"c{sum(map(len, self.installed.values())) + 1}", request.name, listing_id=request.listing_id)
        self.installed.setdefault(owner, {})[info.id] = info
        return info

    def remove(self, owner: str, connector_id: str) -> bool:
        return self.installed.get(owner, {}).pop(connector_id, None) is not None

    async def check(self, owner: str, connector_id: str) -> ConnectorInfo | None:
        return self.get(owner, connector_id)

    async def tools(self, owner: str, connector_ids: list[str]) -> list[ConnectorTool]:
        live = {c.id for c in self.list(owner) if c.status == "connected"}
        return [t for t in self.tools_ if t.connector_id in connector_ids and t.connector_id in live]

    async def call(self, owner: str, connector_id: str, tool: str, arguments: dict) -> ToolResult:
        self.calls.append((owner, connector_id, tool, arguments))
        return self.results.get(tool, ToolResult(f"{tool} done"))

    def database(self, owner: str, connector_id: str) -> None:
        return None  # the fake has no built-in apps

    async def start_oauth(self, owner: str, connector_id: str) -> OAuthStart | None:
        return OAuthStart(authorize_url="https://auth.example.com") if self.get(owner, connector_id) else None

    async def finish_oauth(self, state: str, code: str) -> ConnectorInfo:
        raise NotImplementedError


def business_config(tmp_path: Path) -> BusinessConfig:
    return load_business_config(PROJECT_ROOT / "config" / "model_config.yml").model_copy(
        update={"database": tmp_path / "business.db"})


def workspace(tmp_path: Path, replies=(), hub: FakeHub | None = None) -> tuple[Business, Chat]:
    """A Business on a tmp database and library, a scripted chat model (`replies`) and a fake hub."""
    chat = Chat(list(replies))
    library, assistant = agent.build(config(tmp_path), chat, Embeddings())
    return Business(business_config(tmp_path), library, assistant.chat, hub or FakeHub()), chat
