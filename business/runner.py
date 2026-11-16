"""business/runner.py

Runs an active role assistant on a task: context layers (business/context.py; business, role and team as system
messages, the notes as a delimited user message), then the task, through the shared tool loop (`agent.agent.tool_loop`).

Tools offered:

| Model sees               | Runs                                                       | read_only | Policy        |
|--------------------------|------------------------------------------------------------|-----------|---------------|
| `search_documents`       | index search limited to its knowledge: the organized       | yes       | always runs   |
|                          | documents of its `knowledge` scope (empty lists: every     |           |               |
|                          | organized document) and the workspace's own records        |           |               |
| `browse_knowledge`       | the map of that knowledge: sources, sections, never-read   | yes       | always runs   |
| `read_document`          | one of those sources in full, passage by passage           | yes       | always runs   |
| `read_notes`             | notes on its `shares` topics (offered when it has some)    | yes       | always runs   |
| `post_note`              | a note on one of its `shares` topics, authored by its name | no        | always runs   |
| `<connector>__<tool>`    | `hub.call(owner, connector id, tool, arguments)`           | per tool  | see below     |

Connector tools come from `hub.tools(owner, spec.connectors)` (connected connectors only). The exposed name
follows the providers' rule `^[a-zA-Z0-9_-]{1,64}$`: other characters become `_`, and a name that is too long
or taken ends in a hash of `<connector id>/<tool>`; calls are mapped back through the offered list, so an
unknown or unconnected tool is never run.

Policy for connector tools: `read_only` tools always run. Writes use `policy.tools["<connector id>/<tool>"]`,
else `policy.default`: `auto` runs, `ask` stores a pending `Approval` (reason: the assistant's text of that
turn) and tells the model it is queued, `deny` refuses. Every call is returned as a `ToolRun`.

*Usage:*
>>> context, tools = await assemble(business, owner, info)       # the preview: GET .../context
>>> response = await run(business, owner, info, RunRequest(messages=[...]))
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agent.agent import ToolCall, tool_loop
from agent.schema import ChatMessage
from agent.tools import TOOLS, ToolContext, cap
from business.context import SYSTEM_LAYERS, build_context
from business.schema import AssistantContext, AssistantInfo, NoteCreate, RunRequest, RunResponse, ToolRun
from library.schema import SearchFilters

if TYPE_CHECKING:
    from business.service import Business

log = logging.getLogger(__name__)
RESULT_CHARS = 2000  # ToolRun.result as returned to the client
_INVALID = re.compile(r"[^a-zA-Z0-9_-]")

Builtin = Callable[[dict], Awaitable[str]]


@dataclass
class Offered:
    name: str  # what the model calls
    connector_id: str | None  # None: built-in
    tool: str  # the connector's tool name, or the built-in's name
    read_only: bool
    spec: dict  # {name, description, parameters}
    run: Builtin | None = None  # built-ins

    @property
    def label(self) -> str:
        """As listed in `AssistantContext.tools`."""
        return f"{self.connector_id}/{self.tool}" if self.connector_id else self.tool


def exposed_name(connector_id: str, tool: str, taken: set[str]) -> str:
    """`<connector>__<tool>` with characters outside `[a-zA-Z0-9_-]` as `_`; too long or taken: the first 55
    characters, `_` and 8 hex digits of a hash of `<connector>/<tool>/<n>`, n counting up until the name is free."""
    plain = _INVALID.sub("_", f"{connector_id}__{tool}")
    name, n = plain, 0
    while len(name) > 64 or name in taken:
        name = plain[:55] + "_" + hashlib.sha1(f"{connector_id}/{tool}/{n}".encode()).hexdigest()[:8]
        n += 1
    return name


# --- Built-in tools ------------------------------------------------------------------------------------------


def builtins(business: Business, owner: str, info: AssistantInfo) -> list[Offered]:
    shares = {s.lower(): s for s in info.shares}

    def knowledge_ids() -> list[str]:
        """Organized documents inside the spec's `knowledge` scope, plus the workspace's own index records."""
        scope = info.knowledge
        departments = {d.lower() for d in scope.departments}
        kinds = {k.lower() for k in scope.document_kinds}
        organized = [d.document_id for d in business.documents(owner)
                     if (not departments or (d.department or "").lower() in departments)
                     and (not kinds or d.kind.lower() in kinds)]
        return organized + business.knowledge_ids(owner)

    def knowledge_tool(name: str) -> Builtin:
        async def run(args: dict) -> str:
            ids = await asyncio.to_thread(knowledge_ids)
            if not ids:
                return "No documents are in this assistant's knowledge scope."
            ctx = ToolContext(library=business.library, owner=owner,
                              scope=SearchFilters().model_copy(update={"document_ids": ids}))
            return await TOOLS[name].run(args, ctx)
        return run

    async def read_notes(args: dict) -> str:
        topic = args.get("topic")
        if topic is not None and str(topic).lower() not in shares:
            return f"error: you share only these topics: {', '.join(info.shares)}"
        topics = [shares[str(topic).lower()]] if topic else list(info.shares)
        notes = await asyncio.to_thread(business.store.notes, owner, topics, 20)
        return "\n".join(f"[{n.topic}] {n.author}, {n.created_at:%Y-%m-%d %H:%M}: {n.text}" for n in notes) \
            or "No notes yet."

    async def post_note(args: dict) -> str:
        topic = str(args.get("topic") or "")
        if topic.lower() not in shares:
            return f"error: you can post only on: {', '.join(info.shares)}"
        try:
            request = NoteCreate(topic=shares[topic.lower()], text=args.get("text"))
        except ValidationError as exc:
            return f"error: {exc.errors()[0]['msg']}"
        note = await asyncio.to_thread(business.post_note, owner, request, info.name)
        return f"Posted on {note.topic}."

    described = {
        "search_documents": "Search your knowledge (the business documents in your scope and the workspace's "
                            "records: profile, discovery answers, notes). Returns numbered excerpts.",
        "browse_knowledge": "The map of your knowledge: every source with its sections and how much of it was "
                            "never retrieved. Use it to see what exists beyond what a search returned.",
        "read_document": "Read one source of your knowledge in full, passage by passage.",
    }
    tools = [Offered(name, None, name, True, {**TOOLS[name].spec, "description": text}, knowledge_tool(name))
             for name, text in described.items()]
    if info.shares:
        topic = {"type": "string", "enum": list(info.shares)}
        tools += [
            Offered("read_notes", None, "read_notes", True, {
                "name": "read_notes", "description": "Notes on your shared topics, newest first.",
                "parameters": {"type": "object", "properties": {"topic": topic}}}, read_notes),
            Offered("post_note", None, "post_note", False, {
                "name": "post_note", "description": "Post a fact, hand-off or report for the assistants and people "
                                                    "sharing the topic.",
                "parameters": {"type": "object", "properties": {"topic": topic, "text": {"type": "string"}},
                               "required": ["topic", "text"]}}, post_note),
        ]
    return tools


# --- Assembly and run ------------------------------------------------------------------------------------------


async def offered_tools(business: Business, owner: str, info: AssistantInfo) -> list[Offered]:
    tools = builtins(business, owner, info)
    taken = {t.name for t in tools}
    names = {c.id: c.name for c in await asyncio.to_thread(business.hub.list, owner)}
    for t in await business.hub.tools(owner, info.connectors) if info.connectors else []:
        name = exposed_name(t.connector_id, t.name, taken)
        taken.add(name)
        description = f"[{names.get(t.connector_id, t.connector_id)}] {t.description}".strip()
        tools.append(Offered(name, t.connector_id, t.name, t.read_only,
                             {"name": name, "description": description, "parameters": t.input_schema or
                              {"type": "object", "properties": {}}}))
    return tools


async def assemble(business: Business, owner: str, info: AssistantInfo) -> tuple[AssistantContext, list[Offered]]:
    """The context layers exactly as sent, and the tools offered."""
    tools = await offered_tools(business, owner, info)

    def gather():
        team = [a for a in business.store.assistants(owner) if a.id != info.id]
        notes = business.store.notes(owner, list(info.shares), 50) if info.shares else []
        return business.profile(owner), team, notes

    profile, team, notes = await asyncio.to_thread(gather)
    context = build_context(info, profile, team, notes, business.config.context, business.config.assistant_prompt,
                            [t.label for t in tools])
    return context, tools


async def run(business: Business, owner: str, info: AssistantInfo, request: RunRequest) -> RunResponse:
    await business.sync_memory(owner)  # the workspace's records, current, before the assistant searches
    context, tools = await assemble(business, owner, info)
    by_name = {t.name: t for t in tools}
    messages = [{"role": "system" if layer.name in SYSTEM_LAYERS else "user", "content": layer.text}
                for layer in context.layers]
    messages += [m.model_dump() for m in request.messages]
    runs: list[ToolRun] = []

    async def dispatch(call: ToolCall, text: str) -> str:
        offered = by_name.get(call.name)
        if offered is None:
            result = f"error: unknown tool {call.name!r}"
            runs.append(ToolRun(connector_id=None, tool=call.name, arguments=call.arguments, read_only=False,
                                outcome="failed", result=result))
            return result
        outcome, approval_id = "ran", None
        if offered.run is not None:
            result = await offered.run(call.arguments)
            outcome = "failed" if result.startswith("error:") else "ran"
        else:
            key = offered.label
            mode = "auto" if offered.read_only else info.policy.tools.get(key, info.policy.default)
            if mode == "auto":
                done = await business.hub.call(owner, offered.connector_id, offered.tool, call.arguments)
                outcome = "failed" if done.is_error else "ran"
                result = f"error: {done.text}" if done.is_error else done.text
            elif mode == "deny":
                outcome = "denied"
                result = f"refused: {info.name} may not run {key}. Do not retry it; tell the user it is not allowed."
            else:
                outcome = "pending_approval"
                approval_id = await asyncio.to_thread(
                    business.store.insert_approval, owner, info, offered.connector_id, offered.tool, call.arguments,
                    text.strip() or "No reason given.")
                result = (f"queued for the owner's approval (approval {approval_id}); it has not run yet. Do not call "
                          "it again; tell the user it awaits approval.")
        result = cap(result)
        runs.append(ToolRun(connector_id=offered.connector_id, tool=offered.tool, arguments=call.arguments,
                            read_only=offered.read_only, outcome=outcome, approval_id=approval_id,
                            result=cap(result, RESULT_CHARS)))
        return result

    reply, usage = await tool_loop(business.chat, messages, [t.spec for t in tools], dispatch, info.max_tool_rounds)
    log.info("assistant ran", extra={"ctx": {"assistant": info.id, "tools": [f"{r.tool}:{r.outcome}" for r in runs],
                                             **usage}})
    return RunResponse(message=ChatMessage(role="assistant", content=reply.text.strip() or "The model returned no "
                                                                                          "answer."),
                       tool_runs=runs, model=business.chat.config.model, usage=usage)
