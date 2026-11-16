"""business/schema.py

API models of the business workspace: the business profile and its interview, organized documents, the
knowledge index, connectors (MCP servers and built-in apps), the workspace database app, assistants (a JSON spec
each), approvals, the shared notes board, and the agentic UI (events in, hints out). Every model the routes take
or return is here, so the OpenAPI document (and the dashboard's generated types) follow from this file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.schema import ChatMessage, ChatResponse
from library.schema import Origin, SearchFilters, SearchHit, SourceRef, SourceSummary


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Business profile ------------------------------------------------------------------------


class Department(Strict):
    name: str = Field(min_length=1, max_length=80, description="e.g. Finance, Sales, Operations.")
    purpose: str = Field(default="", max_length=500)
    head: str | None = Field(default=None, description="Title of the role that leads it.")
    responsibilities: list[str] = Field(default_factory=list)


class Role(Strict):
    title: str = Field(min_length=1, max_length=80, description="e.g. Bookkeeper, Sales rep.")
    department: str | None = None
    people: list[str] = Field(default_factory=list, description="Who holds the role (names or 'owner').")
    duties: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list, description="Names from `BusinessProfile.tools`.")
    reports_to: str | None = Field(default=None, description="Title of another role.")


class ToolInUse(Strict):
    name: str = Field(min_length=1, max_length=80, description="e.g. QuickBooks, Gmail, Shopify.")
    category: str = Field(default="", description="e.g. accounting, email, CRM, storefront.")
    used_for: str = Field(default="", max_length=300)
    departments: list[str] = Field(default_factory=list)
    listing_id: str | None = Field(default=None, description="Store listing that connects it, when there is one.")


class InformationFlow(Strict):
    """Information one part of the business passes to another (a report, a hand-off, a shared record)."""

    source: str = Field(description="Department or role that produces it.")
    target: str = Field(description="Department or role that uses it.")
    what: str = Field(description="e.g. weekly sales report, new order, invoice.")
    cadence: str = Field(default="", description="e.g. per order, weekly, month end.")
    via: str = Field(default="", description="Tool or channel, e.g. Slack, a shared sheet.")


class Financials(Strict):
    revenue_streams: list[str] = Field(default_factory=list)
    cost_centers: list[str] = Field(default_factory=list)
    pricing: str = ""
    currency: str = "USD"
    fiscal_year_end: str = Field(default="", description="e.g. December 31.")
    accounting_method: Literal["", "cash", "accrual"] = ""
    reporting: list[str] = Field(default_factory=list, description="Reports the business produces, e.g. monthly P&L.")


class BusinessProfile(Strict):
    """What the partner knows about the business. Filled from the interview and documents; the owner can edit it."""

    name: str = ""
    summary: str = Field(default="", max_length=2000, description="What the business does, in a few sentences.")
    industry: str = ""
    business_model: str = Field(default="", description="How it makes money.")
    offerings: list[str] = Field(default_factory=list, description="Products and services.")
    customers: str = Field(default="", description="Who buys, and how they find the business.")
    locations: list[str] = Field(default_factory=list)
    team_size: int | None = Field(default=None, ge=0)
    stage: str = Field(default="", description="e.g. solo, growing, established.")
    goals: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    departments: list[Department] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    tools: list[ToolInUse] = Field(default_factory=list)
    flows: list[InformationFlow] = Field(default_factory=list)
    financials: Financials = Field(default_factory=Financials)
    compliance: list[str] = Field(default_factory=list, description="Licenses, regulations, filing duties.")
    updated_at: datetime | None = None


# --- Interview -------------------------------------------------------------------------------

Area = Literal["identity", "offering", "customers", "revenue", "operations", "departments", "roles", "finance",
               "sales_marketing", "tools", "data", "information_flow", "compliance", "goals"]


class Question(BaseModel):
    id: str = Field(description="Stable id, e.g. finance.accounting_method.")
    area: Area
    text: str
    purpose: str = Field(description="Why the partner asks: what the answer lets it set up.")
    fills: list[str] = Field(description="Profile fields the answer informs, e.g. financials.accounting_method.")


class AreaProgress(BaseModel):
    area: Area
    label: str
    answered: int
    total: int


class InterviewState(BaseModel):
    answered: int
    total: int
    complete: bool = Field(description="Every area has its required questions answered.")
    areas: list[AreaProgress]
    next: list[Question] = Field(description="What to ask next, most useful first (at most 5).")


class AnswerRequest(Strict):
    question_id: str
    answer: str = Field(min_length=1, max_length=5000)


class Answer(BaseModel):
    question_id: str
    answer: str
    answered_at: datetime


# --- Partner chat ------------------------------------------------------------------------------


class UiEntity(Strict):
    kind: str = Field(description="e.g. document, assistant, connector, approval.")
    id: str
    title: str = ""


class UiState(Strict):
    """What the user is looking at: sent with partner messages and hint requests."""

    page: str = Field(description="Route path, e.g. /connectors.")
    entity: UiEntity | None = None
    detail: dict = Field(default_factory=dict, description="Page-specific state, e.g. {filter: 'pending'}.")


class PartnerRequest(Strict):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    ui_state: UiState | None = Field(default=None, description="The screen the message was sent from.")


class PartnerResponse(ChatResponse):
    profile_changed: bool = Field(description="The partner changed the profile; refetch it.")
    assistants_changed: bool = Field(description="The partner created or changed an assistant.")
    interview: InterviewState


# --- Documents -------------------------------------------------------------------------------


class OrganizedDocument(BaseModel):
    """A library document placed in the business profile by the partner (or the owner)."""

    document_id: str
    title: str
    department: str | None
    kind: str = Field(description="e.g. invoice, contract, SOP, price list, report.")
    summary: str
    organized_at: datetime


class OrganizeRequest(Strict):
    department: str | None = None
    kind: str = Field(min_length=1, max_length=60)
    summary: str = Field(default="", max_length=1000)


# --- Knowledge index ---------------------------------------------------------------------------



class KnowledgeSource(SourceSummary):
    """One source of the index: an uploaded document, or a workspace record (profile, discovery answers, notes)."""

    origin: Origin = Field(description="upload: a file; workspace: what the partner and owner recorded.")
    department: str | None = Field(default=None, description="Where the partner filed it, when organized.")
    kind: str | None = Field(default=None, description="e.g. invoice, contract, SOP; set when organized.")


class KnowledgeMap(BaseModel):
    """Everything the index holds, so nothing depends on being found by a search."""

    sources: int = Field(description="Sources in the index.")
    passages: int = Field(description="Indexed passages over all sources.")
    never_retrieved: int = Field(description="Passages no search or assistant has surfaced yet.")
    count: int = Field(description="Sources matching the request's filters.")
    items: list[KnowledgeSource] = Field(description="A page of the matching sources.")


class KnowledgeSearchRequest(Strict):
    query: str = Field(min_length=1, max_length=2000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int | None = Field(default=None, ge=1)


class KnowledgeSearchResponse(BaseModel):
    hits: list[SearchHit]
    other_sources: list[SourceRef] = Field(
        description="Sources that also matched but have no passage among `hits`: open them to read more.")


# --- Connectors --------------------------------------------------------------------------------

Transport = Literal["streamable_http", "sse", "stdio", "builtin"]
AuthKind = Literal["none", "bearer", "oauth"]


class ConnectorListing(BaseModel):
    """An entry of the connector store."""

    id: str = Field(description="e.g. stripe, google-drive.")
    name: str
    publisher: str
    category: str = Field(description="e.g. Storage, Payments, CRM, Productivity, Data, Automation.")
    also_in: list[str] = Field(default_factory=list, description="Further categories it is listed under.")
    tagline: str = Field(default="", description="One line on what assistants do with it.")
    description: str = Field(description="How to connect it: where its URL and credentials come from.")
    builtin: bool = Field(default=False, description="Runs inside this app: no server, URL or sign-in.")
    capabilities: list[str]
    availability: str = Field(description="As the publisher states it, e.g. 'Official, read-only'.")
    docs_url: str = Field(description="The publisher's setup page; empty for built-in apps.")
    transport: Transport
    url: str | None = Field(description="Server URL for remote servers; None when it depends on the account.")
    auth: AuthKind
    featured: bool = False


class ConnectorCreate(Strict):
    """Add a connector: from the store (`listing_id`) or by hand."""

    listing_id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    transport: Transport = Field(default="streamable_http", description="`builtin` only through a store listing.")
    url: str | None = Field(default=None, description="Remote servers.")
    command: str | None = Field(default=None, description="stdio servers (admin keys only).")
    args: list[str] = Field(default_factory=list)
    auth: AuthKind = "none"
    token: str | None = Field(default=None, description="Bearer token or API key; stored encrypted, never returned.")


ConnectorStatus = Literal["untested", "connected", "needs_auth", "error"]


class ConnectorInfo(BaseModel):
    id: str
    listing_id: str | None
    name: str
    transport: Transport
    url: str | None
    command: str | None
    args: list[str]
    auth: AuthKind
    has_secret: bool
    status: ConnectorStatus
    error: str | None
    tool_count: int
    created_at: datetime
    checked_at: datetime | None


class ConnectorTool(BaseModel):
    connector_id: str
    name: str
    description: str
    read_only: bool = Field(description="The server marks it read-only (MCP `readOnlyHint`); otherwise a write.")
    input_schema: dict


class OAuthStart(BaseModel):
    authorize_url: str = Field(description="Open it; the provider redirects back to /v1/connectors/oauth/callback.")


# --- Workspace database app (business/database.py) ----------------------------------------------

ColumnType = Literal["text", "integer", "real", "date", "boolean"]
CellValue = bool | int | float | str | None


class Column(Strict):
    name: str = Field(min_length=1, max_length=63, description="Letters, digits and _.")
    type: ColumnType = "text"
    required: bool = Field(default=False, description="NOT NULL.")
    primary_key: bool = Field(default=False, description="Set by the database; ignored on create.")


class TableCreate(Strict):
    name: str = Field(min_length=1, max_length=63)
    columns: list[Column] = Field(min_length=1, max_length=100, description="An integer `id` key is added.")


class TableInfo(BaseModel):
    name: str
    columns: list[Column]
    rows: int


class RowPage(BaseModel):
    columns: list[str]
    rowids: list[int] = Field(description="The key of each row, in the order of `rows`; empty for a table "
                                          "without rowids (WITHOUT ROWID), whose rows change through SQL only.")
    rows: list[list[CellValue]]
    total: int = Field(description="Rows in the table.")


class RowWrite(Strict):
    values: dict[str, CellValue] = Field(min_length=1, description="Column name -> value.")


class QueryRequest(Strict):
    sql: str = Field(min_length=1, max_length=20_000, description="One SQLite statement.")
    write: bool = Field(default=False, description="False: SELECT only. True: the statement may change data.")


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[CellValue]]
    truncated: bool = Field(default=False, description="More rows matched than are returned.")
    changed: int = Field(default=0, description="Rows a write statement changed.")


# --- Assistants ----------------------------------------------------------------------------------

WriteMode = Literal["auto", "ask", "deny"]


class WritePolicy(Strict):
    """What happens when the assistant calls a tool that changes something. Reads always run."""

    default: WriteMode = "ask"
    tools: dict[str, WriteMode] = Field(
        default_factory=dict, description="Per tool, keyed `<connector id>/<tool name>`; overrides `default`."
    )


class KnowledgeScope(Strict):
    """Which organized documents the assistant can search. Empty lists: no limit."""

    departments: list[str] = Field(default_factory=list)
    document_kinds: list[str] = Field(default_factory=list)


class AssistantSpec(Strict):
    """
    An assistant is this JSON object. The partner creates them; the owner can write or edit one by hand.

    {"name": "Accountant", "role": "Keeps the books and prepares the monthly report",
     "department": "Finance", "instructions": "...", "connectors": ["<connector id>"],
     "knowledge": {"departments": ["Finance"]}, "shares": ["finance", "month-end"],
     "policy": {"default": "ask", "tools": {"<connector id>/list_invoices": "auto"}}}
    """

    name: str = Field(min_length=1, max_length=60)
    role: str = Field(min_length=1, max_length=300, description="One sentence: what it is responsible for.")
    department: str | None = None
    instructions: str = Field(default="", max_length=8000, description="How it works: steps, rules, tone.")
    connectors: list[str] = Field(default_factory=list, description="Ids of installed connectors it may use.")
    knowledge: KnowledgeScope = Field(default_factory=KnowledgeScope)
    shares: list[str] = Field(default_factory=list,
                              description="Notes-board topics it reads and posts to (shared with other assistants).")
    policy: WritePolicy = Field(default_factory=WritePolicy)
    max_tool_rounds: int = Field(default=6, ge=0, le=20)


AssistantStatus = Literal["draft", "active", "paused"]


class AssistantInfo(AssistantSpec):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: AssistantStatus
    created_by: Literal["owner", "partner"]
    created_at: datetime
    updated_at: datetime


class AssistantStatusRequest(Strict):
    status: AssistantStatus


class AssistantContext(BaseModel):
    """What the assistant's model receives before the task: the layers, in order, as sent."""

    layers: list[ContextLayer]
    tools: list[str] = Field(description="Tool names offered, `<connector id>/<tool>` for connector tools.")
    chars: int


class ContextLayer(BaseModel):
    name: Literal["business", "role", "team", "notes"]
    text: str


class RunRequest(Strict):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50, description="The task or conversation.")


ToolOutcome = Literal["ran", "pending_approval", "denied", "failed"]


class ToolRun(BaseModel):
    connector_id: str | None = Field(description="None for built-in tools (documents, notes).")
    tool: str
    arguments: dict
    read_only: bool
    outcome: ToolOutcome
    approval_id: str | None = None
    result: str = Field(description="What the model read (truncated).")


class RunResponse(BaseModel):
    message: ChatMessage
    tool_runs: list[ToolRun]
    model: str
    usage: dict = Field(default_factory=dict)


# --- Approvals ---------------------------------------------------------------------------------------

ApprovalStatus = Literal["pending", "executing", "rejected", "executed", "failed"]


class Approval(BaseModel):
    id: str
    assistant_id: str
    assistant_name: str
    connector_id: str
    tool: str
    arguments: dict
    reason: str = Field(description="The assistant's own words on why, from its message before the call.")
    status: ApprovalStatus
    result: str | None = Field(description="Tool output once executed, or the error.")
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    note: str | None


class ApprovalDecision(Strict):
    approve: bool
    note: str | None = Field(default=None, max_length=500)
    always: bool = Field(default=False, description="Approve and set this tool to `auto` for the assistant.")


# --- Notes board ------------------------------------------------------------------------------------


class Note(BaseModel):
    """A fact, hand-off or report one assistant (or the owner) shares on a topic."""

    id: str
    topic: str
    text: str
    author: str = Field(description="Assistant name, 'partner' or 'owner'.")
    created_at: datetime


class NoteCreate(Strict):
    topic: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=4000)


# --- Workspace and agentic UI -----------------------------------------------------------------------


class WorkspaceSummary(BaseModel):
    business_name: str
    profile_fields: int = Field(description="Profile sections with content.")
    profile_total: int
    interview: InterviewState
    documents: int
    organized_documents: int
    assistants: dict[AssistantStatus, int]
    connectors: dict[ConnectorStatus, int]
    pending_approvals: int
    recommended_connectors: list[ConnectorListing] = Field(
        description="Store listings for tools the business uses that are not installed yet."
    )


UiEventType = Literal["navigate", "select", "action", "error", "idle"]


class UiEvent(Strict):
    type: UiEventType
    page: str
    target: str | None = Field(default=None, description="What was acted on, e.g. 'button:Upload' or an entity id.")
    detail: dict = Field(default_factory=dict)
    at: datetime


class HintsRequest(Strict):
    state: UiState
    events: list[UiEvent] = Field(default_factory=list, max_length=50, description="Recent events, oldest first.")


class HintAction(BaseModel):
    label: str
    href: str = Field(description="Dashboard path to open, e.g. /connectors?add=stripe.")


class Hint(BaseModel):
    id: str = Field(description="Stable per suggestion, so the dashboard can remember dismissals.")
    title: str
    body: str
    tone: Literal["info", "suggestion", "warning"]
    action: HintAction | None = None


class HintsResponse(BaseModel):
    hints: list[Hint] = Field(description="Most relevant first, at most 3.")


AssistantContext.model_rebuild()
PartnerResponse.model_rebuild()
