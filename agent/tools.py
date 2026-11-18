"""agent/tools.py

Tools the assistants can call over the document library. A `Tool` is a name, a description, JSON-schema
parameters and an async handler `(args, ctx) -> str` returning the text the model reads. `TOOLS` is the registry
the document assistant offers to the model and dispatches from; the partner and role assistants offer the same
tools inside their own scope.

| Tool                | Does                                                                       |
|---------------------|----------------------------------------------------------------------------|
| `search_documents`  | hybrid search; every excerpt gets a source number the answer cites as [n]  |
| `browse_knowledge`  | the map of the index: every source, its sections, what was never retrieved |
| `read_document`     | a source in full, passage by passage, numbered like search excerpts        |
| `list_documents`    | the stored documents: id, title, type, pages, passages, when added         |

Every tool is read-only and runs inside the caller's API key (`ctx.owner`) and the scope (`ctx.scope`: when it
names documents, nothing else is visible). Invalid arguments come back to the model as `error: ...` text instead
of failing the request.

Adding a tool: write `async def handler(args: dict, ctx: ToolContext) -> str`, decorate it with
`@tool(name, description, parameters)`, and mention it in the system prompt (`config/model_config.yml`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi.concurrency import run_in_threadpool

from agent.schema import Source
from library.schema import WORKSPACE_PREFIX, DocumentDetail, DocumentFilters, SearchFilters, SearchHit
from library.service import Library

MAX_CHARS = 12_000  # per tool result
BROWSE_LIMIT, READ_LIMIT, LIST_LIMIT = 30, 8, 50  # sources per browse page, passages per read, documents per list


@dataclass
class ToolContext:
    library: Library
    scope: SearchFilters
    owner: str | None  # API key id; None: admin (every owner)
    sources: dict[str, Source] = field(default_factory=dict)  # chunk id -> numbered source, per conversation turn


Handler = Callable[[dict, ToolContext], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Handler

    @property
    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, parameters: dict) -> Callable[[Handler], Handler]:
    """Register a handler in `TOOLS`."""
    def register(handler: Handler) -> Handler:
        TOOLS[name] = Tool(name, description, parameters, handler)
        return handler
    return register


# --- Scope and arguments -------------------------------------------------------------------------


def scoped(ctx: ToolContext, q: object = None) -> DocumentFilters:
    """The documents a tool may see: the scope's, optionally narrowed to titles containing `q`."""
    title = q.strip()[:200] if isinstance(q, str) and q.strip() else None
    return DocumentFilters(q=title).model_copy(update={"document_ids": ctx.scope.document_ids})


async def scoped_document(args: dict, ctx: ToolContext) -> DocumentDetail | str:
    """The document named by `document_id` if the key may read it and it is inside the scope."""
    doc_id = args.get("document_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        return "error: `document_id` is required"
    missing = f"error: no document {doc_id} in this conversation's scope"
    if ctx.scope.document_ids and doc_id not in ctx.scope.document_ids:
        return missing
    return await run_in_threadpool(ctx.library.get, doc_id, ctx.owner) or missing


def cap(text: str, limit: int = MAX_CHARS) -> str:
    """`text` cut to `limit` characters, then `\n[truncated]` appended when it was cut."""
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"


def _count(args: dict, key: str, default: int, most: int) -> int:
    value = args.get(key)
    return min(value, most) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _offset(args: dict) -> int:
    value = args.get("offset")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _label(hit: SearchHit) -> str:
    """'handbook (Refund policy, page 2)': what the model sees above each excerpt."""
    details = [hit.section_title, f"page {hit.page_number}" if hit.page_number else "",
               f"sheet {hit.sheet_name}" if hit.sheet_name and hit.sheet_name != hit.section_title else ""]
    details = ", ".join(d for d in details if d)
    return f"{hit.title} ({details})" if details else hit.title


def _cite(hit: SearchHit, ctx: ToolContext) -> str:
    """The excerpt as the model reads it, under the source number its answer cites."""
    source = ctx.sources.setdefault(hit.chunk_id, Source(n=len(ctx.sources) + 1, **hit.model_dump()))
    return f"[{source.n}] {_label(hit)} [document {hit.document_id}]\n{hit.content}"


DOCUMENT_ID = {"document_id": {"type": "string", "description": "Document id, from search results, "
                                                                "browse_knowledge or list_documents."}}
PAGING = {"limit": {"type": "integer", "minimum": 1, "maximum": 100},
          "offset": {"type": "integer", "minimum": 0, "description": "Skip this many (next page)."}}


# --- Tools -------------------------------------------------------------------------------------


@tool("search_documents",
      "Search everything stored (uploaded business documents and the workspace's own records: business profile, "
      "discovery answers, notes) by meaning and by keywords. Returns numbered excerpts with their document id, "
      "section and page, and names other sources that are relevant but not shown.",
      {"type": "object", "properties": {
          "query": {"type": "string", "description": "What to look for, in words or exact terms "
                                                     "(e.g. 'payment terms for wholesale', 'invoice 2025-0042')."},
          "limit": {"type": "integer", "minimum": 1, "description": "Number of excerpts (capped by the server)."},
      }, "required": ["query"]})
async def search_documents(args: dict, ctx: ToolContext) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return "error: `query` is required"
    limit = args.get("limit") if isinstance(args.get("limit"), int) else None
    found = await ctx.library.search_wide(query, ctx.scope, ctx.owner, limit)
    if not found.hits:
        return "No matching documents. browse_knowledge lists everything that is stored."
    out = [_cite(hit, ctx) for hit in found.hits]
    if found.other_sources:
        out.append("Also relevant, not shown (open with read_document): "
                   + "; ".join(f"{s.title} [document {s.document_id}]" for s in found.other_sources))
    return "\n\n".join(out)


@tool("browse_knowledge",
      "The map of everything stored, whether or not a search finds it: every source (uploaded documents, and the "
      "workspace's own records: business profile, discovery answers, notes) with its sections, its number of "
      "passages and how many were never retrieved. Use it to see what exists before concluding something is "
      "unknown; `unused_only` lists the material nobody has looked at yet. Open a source with read_document.",
      {"type": "object", "properties": {
          "q": {"type": "string", "description": "Only sources whose title contains this text."},
          "unused_only": {"type": "boolean", "description": "Only sources with passages never retrieved."},
          **PAGING,
      }})
async def browse_knowledge(args: dict, ctx: ToolContext) -> str:
    limit, offset = _count(args, "limit", BROWSE_LIMIT, 100), _offset(args)
    found = await run_in_threadpool(ctx.library.sources, scoped(ctx, args.get("q")), ctx.owner, limit, offset,
                                    args.get("unused_only") is True)
    head = (f"{found.sources} source(s), {found.passages} passage(s), {found.never_retrieved} never retrieved. "
            f"{found.count} match")
    if not found.items:
        return head + "; none on this page."
    lines = [head + f"; showing {offset + 1}-{offset + len(found.items)}:"]
    for s in found.items:
        kind = "workspace record" if s.location.startswith(WORKSPACE_PREFIX) else f"{s.type} file"
        sections = f" | sections: {'; '.join(s.sections)}" if s.sections else ""
        lines.append(f"- {s.document_id} | {s.title} | {kind} | {s.passages} passage(s), "
                     f"{s.never_retrieved} never retrieved{sections}")
    return cap("\n".join(lines))


@tool("read_document",
      "Read a source in full, passage by passage in document order (a search returns only its best excerpts). "
      "Passages are numbered like search excerpts, so cite them the same way. `offset` continues after the "
      "passages already read.",
      {"type": "object", "properties": {
          **DOCUMENT_ID,
          "offset": {"type": "integer", "minimum": 0, "description": "Passages to skip (0: from the start)."},
          "limit": {"type": "integer", "minimum": 1, "maximum": 20},
      }, "required": ["document_id"]})
async def read_document(args: dict, ctx: ToolContext) -> str:
    document = await scoped_document(args, ctx)
    if isinstance(document, str):
        return document
    limit, offset = _count(args, "limit", READ_LIMIT, 20), _offset(args)
    read = await run_in_threadpool(ctx.library.passages, document.id, ctx.owner, limit, offset, True)
    if read is None or not read.passages:
        return f"{document.title} has {read.count if read else 0} passage(s); none at offset {offset}."
    out = [f"{document.title}: passages {offset + 1}-{offset + len(read.passages)} of {read.count}."]
    for p in read.passages:
        hit = SearchHit(chunk_id=p.chunk_id, document_id=document.id, title=document.title,
                        section_title=p.section_title, page_number=p.page_number, sheet_name=p.sheet_name,
                        content=p.content, similarity=None)
        out.append(_cite(hit, ctx))
    rest = read.count - offset - len(read.passages)
    if rest > 0:
        out.append(f"{rest} more passage(s): call read_document with offset {offset + len(read.passages)}.")
    return cap("\n\n".join(out))


@tool("list_documents",
      "List the stored documents, newest first: id, title, file type, pages, passages and when each was added. "
      "Workspace records (business profile, discovery answers, notes) are included.",
      {"type": "object", "properties": {
          "q": {"type": "string", "description": "Only documents whose title contains this text."},
          **PAGING,
      }})
async def list_documents(args: dict, ctx: ToolContext) -> str:
    limit, offset = _count(args, "limit", LIST_LIMIT, 100), _offset(args)
    total, documents = await run_in_threadpool(ctx.library.list, scoped(ctx, args.get("q")), ctx.owner, limit, offset)
    shown = f"; showing {offset + 1}-{offset + len(documents)}:" if total > len(documents) else ":"
    lines = [f"{total} document(s) match" + shown]
    for d in documents:
        kind = "workspace record" if d.location.startswith(WORKSPACE_PREFIX) else f"{d.type} file"
        pages = f"{d.page_count} page(s), " if d.page_count else ""
        lines.append(f"- {d.id} | {d.title} | {kind} | {pages}{d.chunks} passage(s) | added {d.created_at:%Y-%m-%d}")
    return cap("\n".join(lines))
