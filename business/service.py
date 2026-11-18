"""business/service.py

`Business`: one method per use case of the workspace; what the routes call. It ties the workspace store, the
document library, the chat model and the connector hub together; the interview, context, partner, runner and
hints logic lives in the modules named in each method.

Every method takes `owner` (`api.deps.business_owner`: the API key id); nothing crosses workspaces.

*Usage:*
>>> business = Business(load_business_config(path), library, ChatClient(config.chat), hub)
>>> state = business.answer("7", AnswerRequest(question_id="identity.name", answer="Keystone Bakery"))
>>> response = await business.partner_chat("7", PartnerRequest(messages=[...]))
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from typing import get_args

from agent.agent import ChatClient
from business import hints as hint_rules
from business import memory, partner, runner
from business.config import BusinessConfig
from business.connectors import ConnectorHub
from business.errors import AlreadyDecided, InvalidSpec, NotActive
from business.questions import QUESTIONS, interview_state
from business.schema import (
    AnswerRequest,
    Approval,
    ApprovalDecision,
    ApprovalStatus,
    AssistantContext,
    AssistantInfo,
    AssistantSpec,
    AssistantStatus,
    BusinessProfile,
    ConnectorStatus,
    HintsRequest,
    HintsResponse,
    InterviewState,
    KnowledgeMap,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSource,
    Note,
    NoteCreate,
    OrganizedDocument,
    OrganizeRequest,
    PartnerRequest,
    PartnerResponse,
    RunRequest,
    RunResponse,
    WorkspaceSummary,
)
from business.store import Store
from library.schema import WORKSPACE_PREFIX, DocumentFilters, PassageList
from library.search import EmbeddingsUnavailable
from library.service import Library
from library.store import IndexMismatch

log = logging.getLogger(__name__)
UPLOADS = DocumentFilters(origin="upload")  # the owner's files, without the workspace's own index records
PROFILE_SECTIONS = [f for f in BusinessProfile.model_fields if f != "updated_at"]


class Business:
    def __init__(self, config: BusinessConfig, library: Library, chat: ChatClient, hub: ConnectorHub):
        self.config = config
        self.library = library
        self.chat = chat
        self.hub = hub
        self.store = Store(config.database)
        self._memory_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # --- profile and interview ---------------------------------------------------------------

    def profile(self, owner: str) -> BusinessProfile:
        stored = self.store.profile(owner)
        return BusinessProfile.model_validate(stored) if stored else BusinessProfile()

    def save_profile(self, owner: str, profile: BusinessProfile) -> BusinessProfile:
        profile = profile.model_copy(update={"updated_at": datetime.now(UTC)})
        self.store.save_profile(owner, profile.model_dump(mode="json"))
        return profile

    def interview(self, owner: str) -> InterviewState:
        """business/questions.py `interview_state` over the stored answers and profile."""
        return interview_state(self.store.answers(owner), self.profile(owner))

    def answer(self, owner: str, request: AnswerRequest) -> InterviewState:
        """`KeyError` for an unknown question id."""
        if request.question_id not in QUESTIONS:
            raise KeyError(request.question_id)
        self.store.save_answer(owner, request.question_id, request.answer)
        return self.interview(owner)

    async def partner_chat(self, owner: str, request: PartnerRequest) -> PartnerResponse:
        """business/partner.py `chat`."""
        return await partner.chat(self, owner, request)

    # --- knowledge index ------------------------------------------------------------------------

    def memory_lock(self, owner: str) -> asyncio.Lock:
        """Serialises `memory.sync` per owner (in this process)."""
        return self._memory_locks[owner]

    async def sync_memory(self, owner: str, strict: bool = False) -> None:
        """business/memory.py `sync`: profile, discovery answers and notes into the vector index. Unless
        `strict`, an unavailable embedding model only logs: the caller's own search reports it."""
        try:
            await memory.sync(self, owner)
        except (EmbeddingsUnavailable, IndexMismatch) as exc:
            if strict:
                raise
            log.warning("workspace memory not synced", extra={"ctx": {"error": str(exc)}})

    async def knowledge(self, owner: str, filters: DocumentFilters, limit: int, offset: int,
                        unused_only: bool) -> KnowledgeMap:
        """The whole index by source (uploads and workspace records), with what was never retrieved."""
        await self.sync_memory(owner)

        def read() -> KnowledgeMap:
            found = self.library.sources(filters, owner, limit, offset, unused_only)
            organized = {d.document_id: d for d in self.store.organized(owner)}
            items = [KnowledgeSource(
                **source.model_dump(), origin="workspace" if source.location.startswith(WORKSPACE_PREFIX) else "upload",
                department=placed.department if (placed := organized.get(source.document_id)) else None,
                kind=placed.kind if placed else None) for source in found.items]
            return KnowledgeMap(sources=found.sources, passages=found.passages, never_retrieved=found.never_retrieved,
                                count=found.count, items=items)

        return await asyncio.to_thread(read)

    def passages(self, owner: str, document_id: str, limit: int, offset: int) -> PassageList | None:
        """A source's passages in full, as the index holds them; None when it is not the owner's."""
        return self.library.passages(document_id, owner, limit, offset)

    async def search(self, owner: str, request: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
        """Search uploads and workspace records together; `other_sources` names what matched but is not shown."""
        await self.sync_memory(owner, strict=True)
        found = await self.library.search_wide(request.query, request.filters, owner, request.limit)
        return KnowledgeSearchResponse(hits=found.hits, other_sources=found.other_sources)

    def knowledge_ids(self, owner: str) -> list[str]:
        """Ids of the workspace's own records in the index (every assistant may search them)."""
        return [d.id for d in self.library.list(DocumentFilters(origin="workspace"), owner, 10, 0)[1]]

    # --- documents ------------------------------------------------------------------------------

    def _library_ids(self, owner: str, ids: list[str]) -> set[str]:
        """Which of `ids` are still in the owner's library."""
        if not ids:
            return set()
        filters = DocumentFilters().model_copy(update={"document_ids": ids})
        return {d.id for d in self.library.list(filters, owner, len(ids), 0)[1]}

    def documents(self, owner: str) -> list[OrganizedDocument]:
        """Organized documents still in the library, newest first."""
        organized = self.store.organized(owner)
        present = self._library_ids(owner, [d.document_id for d in organized])
        return [d for d in organized if d.document_id in present]

    def organize(self, owner: str, document_id: str, request: OrganizeRequest) -> OrganizedDocument | None:
        """None when the document does not exist for this owner."""
        document = self.library.get(document_id, owner)
        if document is None:
            return None
        placed = OrganizedDocument(document_id=document.id, title=document.title, department=request.department,
                                   kind=request.kind, summary=request.summary, organized_at=datetime.now(UTC))
        self.store.organize(owner, placed)
        return placed

    # --- assistants -----------------------------------------------------------------------------

    @staticmethod
    def assistant_schema() -> dict:
        """JSON Schema of `AssistantSpec`."""
        return AssistantSpec.model_json_schema()

    def assistants(self, owner: str) -> list[AssistantInfo]:
        return self.store.assistants(owner)

    def assistant(self, owner: str, assistant_id: str) -> AssistantInfo | None:
        return self.store.assistant(owner, assistant_id)

    def _check(self, owner: str, spec: AssistantSpec) -> None:
        """`InvalidSpec` for connectors the owner has not installed and policy keys outside them."""
        missing = [c for c in spec.connectors if self.hub.get(owner, c) is None]
        if missing:
            raise InvalidSpec(f"Connector(s) not installed: {', '.join(missing)}.")
        stray = [k for k in spec.policy.tools if k.split("/", 1)[0] not in spec.connectors or "/" not in k]
        if stray:
            raise InvalidSpec(f"Policy keys must be '<connector id>/<tool>' of the assistant's connectors: "
                              f"{', '.join(stray)}.")

    def create_assistant(self, owner: str, spec: AssistantSpec, created_by: str = "owner") -> AssistantInfo:
        """`InvalidSpec` (422) when the spec names a connector the owner has not installed, or a duplicate name."""
        self._check(owner, spec)
        try:
            assistant_id = self.store.insert_assistant(owner, spec, created_by)
        except sqlite3.IntegrityError:
            raise InvalidSpec(f"An assistant named {spec.name!r} already exists.") from None
        return self.store.assistant(owner, assistant_id)

    def update_assistant(self, owner: str, assistant_id: str, spec: AssistantSpec,
                         status: AssistantStatus | None = None) -> AssistantInfo | None:
        """Replace the spec; `status` (the partner passes `draft`) is set in the same statement, else kept."""
        if self.store.assistant(owner, assistant_id) is None:
            return None
        self._check(owner, spec)
        try:
            self.store.update_assistant(owner, assistant_id, spec, status)
        except sqlite3.IntegrityError:
            raise InvalidSpec(f"An assistant named {spec.name!r} already exists.") from None
        return self.store.assistant(owner, assistant_id)

    def set_status(self, owner: str, assistant_id: str, status: AssistantStatus) -> AssistantInfo | None:
        return self.store.assistant(owner, assistant_id) if self.store.set_status(owner, assistant_id, status) else None

    def delete_assistant(self, owner: str, assistant_id: str) -> bool:
        return self.store.delete_assistant(owner, assistant_id)

    async def context(self, owner: str, assistant_id: str) -> AssistantContext | None:
        """business/runner.py `assemble`: the layers and tools exactly as a run sends them."""
        info = self.store.assistant(owner, assistant_id)
        return (await runner.assemble(self, owner, info))[0] if info else None

    async def run(self, owner: str, assistant_id: str, request: RunRequest) -> RunResponse | None:
        """`NotActive` (409) unless the assistant is active."""
        info = self.store.assistant(owner, assistant_id)
        if info is None:
            return None
        if info.status != "active":
            raise NotActive(f"{info.name} is {info.status}; activate it to run it.")
        return await runner.run(self, owner, info, request)

    # --- approvals and notes ------------------------------------------------------------------

    def approvals(self, owner: str, status: ApprovalStatus | None) -> list[Approval]:
        return self.store.approvals(owner, status)

    async def decide(self, owner: str, approval_id: str, decision: ApprovalDecision, reviewer: str) -> Approval | None:
        """Approve (run the call, record the result) or reject. `AlreadyDecided` (409) unless pending.
        An approval is claimed (`pending -> executing`, or `-> rejected`) in one statement before anything runs, so
        concurrent decisions (any process) run the call at most once; `always` applies only to an executed call."""
        approval = self.store.approval(owner, approval_id)
        if approval is None:
            return None
        claimed = "executing" if decision.approve else "rejected"  # one statement: only one decision wins
        if not self.store.decide(owner, approval_id, claimed, None, reviewer, decision.note):
            raise AlreadyDecided(f"Approval {approval_id} is already {self.store.approval(owner, approval_id).status}.")
        if decision.approve:
            done = await self.hub.call(owner, approval.connector_id, approval.tool, approval.arguments)
            status = "failed" if done.is_error else "executed"
            self.store.decide(owner, approval_id, status, done.text, reviewer, decision.note, current="executing")
            if decision.always and status == "executed":
                self._always(owner, approval)
        return self.store.approval(owner, approval_id)

    def _always(self, owner: str, approval: Approval) -> None:
        """Set the approved tool to `auto` in the assistant's policy, while the assistant exists and still has the
        connector."""
        info = self.store.assistant(owner, approval.assistant_id)
        if info is None or approval.connector_id not in info.connectors:
            return
        spec = AssistantSpec.model_validate(info.model_dump(include=set(AssistantSpec.model_fields)))
        spec.policy.tools[f"{approval.connector_id}/{approval.tool}"] = "auto"
        self.store.update_assistant(owner, info.id, spec)

    def notes(self, owner: str, topic: str | None) -> list[Note]:
        return self.store.notes(owner, [topic] if topic else None)

    def post_note(self, owner: str, request: NoteCreate, author: str = "owner") -> Note:
        return self.store.insert_note(owner, request.topic, request.text, author)

    # --- workspace --------------------------------------------------------------------------------

    def _workspace(self, owner: str) -> tuple[hint_rules.Workspace, BusinessProfile]:
        profile = self.profile(owner)
        connectors = self.hub.list(owner)
        documents = self.library.list(UPLOADS, owner, 1, 0)[0]
        pending = self.store.approvals(owner, "pending")  # newest first
        workspace = hint_rules.Workspace(
            interview=interview_state(self.store.answers(owner), profile), documents=documents,
            unorganized=documents - len(self.documents(owner)),
            recommended=hint_rules.recommendations(profile, self.hub.catalog(), connectors),
            connectors=connectors, assistants=self.store.assistants(owner),
            pending_approvals=len(pending), newest_approval=pending[0].id if pending else None)
        return workspace, profile

    def summary(self, owner: str) -> WorkspaceSummary:
        ws, profile = self._workspace(owner)
        filled = [s for s in PROFILE_SECTIONS
                  if getattr(profile, s) != BusinessProfile.model_fields[s].get_default(call_default_factory=True)]
        return WorkspaceSummary(
            business_name=profile.name, profile_fields=len(filled), profile_total=len(PROFILE_SECTIONS),
            interview=ws.interview, documents=ws.documents, organized_documents=ws.documents - ws.unorganized,
            assistants={s: sum(a.status == s for a in ws.assistants) for s in get_args(AssistantStatus)},
            connectors={s: sum(c.status == s for c in ws.connectors) for s in get_args(ConnectorStatus)},
            pending_approvals=ws.pending_approvals, recommended_connectors=[listing for _, listing in ws.recommended])

    def hints(self, owner: str, request: HintsRequest) -> HintsResponse:
        """business/hints.py `hints` over the owner's workspace, the screen and the recent events."""
        return HintsResponse(hints=hint_rules.hints(self._workspace(owner)[0], request.state, request.events))

