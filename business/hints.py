"""business/hints.py

Contextual hints for the dashboard, and connector recommendations. Pure functions: the service gathers the
`Workspace` (one owner's state), the dashboard sends its `UiState` and recent `UiEvent`s.

Rules (`RULES`, each `(workspace, state, events) -> (priority, Hint) | None`; lower priority = more relevant):

| Hint id                     | When                                                        | Action               |
|-----------------------------|-------------------------------------------------------------|----------------------|
| `repeated-error:<page>`     | the same error event 2+ times within 10 minutes             | /partner             |
| `idle:<page pattern>`       | the latest event is `idle` on the current page              | none (explains page) |
| `connector-status:<id>`     | an installed connector is `needs_auth` or `error`           | /connectors          |
| `approvals`                 | approvals are pending                                       | /approvals           |
| `draft:<assistant id>`      | an assistant is a draft (the first by name)                 | /assistants/<id>     |
| `interview`                 | the interview is not complete                               | /partner             |
| `organize-documents`        | library documents are not organized into the profile        | /partner             |
| `connector:<listing id>`    | a profile tool has a store listing that is not installed    | /connectors?add=<id> |
| `first-assistant`           | no assistants and the interview is at least half done       | /partner             |

A hint whose action opens a page in the current section (`/assistants/x` while on `/assistants`) gains
relevance; an action pointing at exactly the current page is dropped (the hint stays). At most 3, most
relevant first; ties keep the table order.

*Usage:*
>>> hints(workspace, UiState(page="/connectors"), events)
[Hint(id='connector-status:...', ...), ...]
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from business.schema import (
    AssistantInfo,
    BusinessProfile,
    ConnectorInfo,
    ConnectorListing,
    Hint,
    HintAction,
    InterviewState,
    ToolInUse,
    UiEvent,
    UiState,
)

MAX_HINTS = 3
ERROR_WINDOW = timedelta(minutes=10)

PAGES: dict[str, str] = {
    "/": "The overview: interview progress, documents, assistants, connectors and approvals at a glance.",
    "/partner": "Talk to the business partner. It interviews you about the business, records what it learns in "
                "the profile, organizes uploaded documents, recommends connectors and drafts assistants.",
    "/profile": "What every assistant knows about the business. The partner fills it from the interview; edit "
                "any section yourself.",
    "/assistants": "Each assistant is a JSON spec: role, instructions, connectors, knowledge, shared notes "
                   "topics and a write policy. Drafts run only once you activate them.",
    "/assistants/:id": "Give the assistant a task. Reads always run; writes follow its policy: auto runs, ask "
                       "queues an approval, deny refuses. The context preview shows exactly what its model reads.",
    "/approvals": "Write actions assistants asked to run. Approve runs the call now, Always also lets that "
                  "assistant run the tool without asking, Reject drops it.",
    "/notes": "The notes board: assistants post facts and hand-offs per topic; assistants sharing a topic read them.",
    "/connectors": "Connectors are what assistants act through: cloud storage and business tools (MCP servers) "
                   "and built-in apps like the workspace database. Add one, sign in when asked, and check that it "
                   "lists its tools.",
    "/documents": "Every uploaded document. Tax forms are extracted for review; business documents become "
                  "searchable knowledge once organized into the profile.",
    "/knowledge": "Everything the assistants can search: your files and what the partner recorded about the "
                  "business. Each source shows how much of it was never retrieved, so rarely used material stays "
                  "in view; open a source to read its passages.",
    "/databases": "Your own databases: create tables, import a CSV, edit rows or run SQL. Assistants given a "
                  "database read it freely; their writes follow their policy.",
    "/documents/:id": "Review the extracted values against the original pages; flagged values need a decision "
                      "before the form can be approved.",
    "/assistant": "Ask questions about the stored documents; answers cite the excerpts they come from.",
    "/settings": "Settings of this dashboard and its connection to the API.",
}


@dataclass
class Workspace:
    """One owner's state, as the hint rules read it."""

    interview: InterviewState
    documents: int
    unorganized: int
    recommended: list[tuple[str, ConnectorListing]]  # (profile tool name, listing not installed)
    connectors: list[ConnectorInfo]
    assistants: list[AssistantInfo]
    pending_approvals: int
    newest_approval: str | None = None  # id of the newest pending approval: part of the hint id


# --- Connector recommendations ----------------------------------------------------------------------


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def match(tool: ToolInUse, listing: ConnectorListing) -> str | None:
    """How a store listing matches a tool the business uses: `name` (named or linked), `capability` (the tool
    is named in its capabilities), `category`, or None."""
    name, listing_names = _key(tool.name), (_key(listing.name), _key(listing.id))
    if tool.listing_id == listing.id or (len(name) >= 3 and any(name in n or n in name for n in listing_names
                                                                  if len(n) >= 3)):
        return "name"
    words = re.compile(rf"\b{re.escape(tool.name.lower())}\b")
    if any(words.search(c.lower()) for c in listing.capabilities):
        return "capability"
    if tool.category and tool.category.lower() == listing.category.lower():
        return "category"
    return None


def matches(profile: BusinessProfile, catalog: list[ConnectorListing], kinds: tuple[str, ...] = (
        "name", "capability", "category")) -> list[tuple[ToolInUse, ConnectorListing, str]]:
    """(tool, listing, how) per profile tool, in profile and catalog order; category matches only for tools
    without a name or capability match."""
    out = []
    for tool in profile.tools:
        found = [(listing, how) for listing in catalog if (how := match(tool, listing)) in kinds]
        strong = [(listing, how) for listing, how in found if how != "category"]
        out += [(tool, listing, how) for listing, how in (strong or found)]
    return out


def recommendations(profile: BusinessProfile, catalog: list[ConnectorListing],
                    installed: list[ConnectorInfo]) -> list[tuple[str, ConnectorListing]]:
    """(tool name, listing) for listings named by the profile's tools that are not installed; each listing once."""
    have = {c.listing_id for c in installed if c.listing_id}
    seen: set[str] = set()
    out = []
    for tool, listing, _ in matches(profile, catalog, ("name", "capability")):
        if listing.id not in have and listing.id not in seen:
            seen.add(listing.id)
            out.append((tool.name, listing))
    return out


# --- Rules -----------------------------------------------------------------------------------------------

Rule = Callable[[Workspace, UiState, list[UiEvent]], "tuple[float, Hint] | None"]


def page_pattern(page: str) -> str:
    """'/assistants/abc' -> '/assistants/:id'; other paths unchanged (query and trailing slash dropped)."""
    path = page.split("?")[0].rstrip("/") or "/"
    for section in ("/assistants", "/documents"):
        if path.startswith(section + "/"):
            return section + "/:id"
    return path


def _utc(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)  # clients may omit the offset


def repeated_error(ws: Workspace, state: UiState, events: list[UiEvent]):
    errors = [e for e in events if e.type == "error"]
    if not errors:
        return None
    latest = max(_utc(e.at) for e in events)
    recent = Counter((e.page, e.target, str(e.detail.get("code") or e.detail.get("message") or ""))
                     for e in errors if latest - _utc(e.at) <= ERROR_WINDOW)
    (page, target, what), count = recent.most_common(1)[0]
    if count < 2:
        return None
    return -10, Hint(id=f"repeated-error:{page_pattern(page)}", tone="warning", title="This keeps failing",
                     body=f"{what or target or 'The same error'} happened {count} times. The partner can look at "
                          "what is going wrong and suggest a way around it.",
                     action=HintAction(label="Ask the partner", href="/partner"))


def idle(ws: Workspace, state: UiState, events: list[UiEvent]):
    if not events or events[-1].type != "idle" or page_pattern(events[-1].page) != page_pattern(state.page):
        return None
    pattern = page_pattern(state.page)
    text = PAGES.get(pattern)
    return (-6, Hint(id=f"idle:{pattern}", tone="info", title="What this page does", body=text)) if text else None


def connector_status(ws: Workspace, state: UiState, events: list[UiEvent]):
    broken = [c for c in ws.connectors if c.status in ("needs_auth", "error")]
    if not broken:
        return None
    c = broken[0]
    body = (f"{c.name} needs you to sign in before assistants can use it." if c.status == "needs_auth"
            else f"{c.name} failed its last check: {(c.error or 'unknown error').rstrip('.')}.")
    if len(broken) > 1:
        body += f" {len(broken) - 1} more connector(s) need attention."
    return 1, Hint(id=f"connector-status:{c.id}", tone="warning",
                   title=f"{c.name} needs sign-in" if c.status == "needs_auth" else f"{c.name} is not working",
                   body=body, action=HintAction(label="Open connectors", href="/connectors"))


def approvals(ws: Workspace, state: UiState, events: list[UiEvent]):
    n = ws.pending_approvals
    if not n:
        return None
    return 2, Hint(id=f"approvals:{ws.newest_approval}", tone="warning", title=f"{n} action(s) await your approval",
                   body="Assistants queued write actions that run only once you approve them.",
                   action=HintAction(label="Review approvals", href="/approvals"))


def drafts(ws: Workspace, state: UiState, events: list[UiEvent]):
    pending = sorted((a for a in ws.assistants if a.status == "draft"), key=lambda a: a.name.lower())
    if not pending:
        return None
    a = pending[0]
    more = f" {len(pending) - 1} more draft(s) wait too." if len(pending) > 1 else ""
    return 4, Hint(id=f"draft:{a.id}", tone="suggestion", title=f"{a.name} is a draft",
                   body=f"Review its role, connectors and write policy, then activate it.{more}",
                   action=HintAction(label=f"Open {a.name}", href=f"/assistants/{a.id}"))


def interview(ws: Workspace, state: UiState, events: list[UiEvent]):
    i = ws.interview
    if i.complete:
        return None
    nxt = f" Next: {i.next[0].text}" if i.next else ""
    return 5, Hint(id="interview", tone="suggestion", title="Tell the partner about the business",
                   body=f"{i.answered} of {i.total} interview questions are covered (answered, or already in the "
                        f"profile).{nxt}",
                   action=HintAction(label="Continue the interview", href="/partner"))


def unorganized(ws: Workspace, state: UiState, events: list[UiEvent]):
    n = ws.unorganized
    if not n:
        return None
    return 6, Hint(id="organize-documents", tone="suggestion", title=f"{n} document(s) are not organized",
                   body="The partner can file them by department and kind so assistants can search them.",
                   action=HintAction(label="Ask the partner", href="/partner"))


def recommended(ws: Workspace, state: UiState, events: list[UiEvent]):
    if not ws.recommended:
        return None
    tool, listing = ws.recommended[0]
    return 7, Hint(id=f"connector:{listing.id}", tone="suggestion", title=f"Connect {listing.name}",
                   body=f"Your profile lists {tool}; with the {listing.name} connector assistants can work in it.",
                   action=HintAction(label=f"Add {listing.name}", href=f"/connectors?add={listing.id}"))


def first_assistant(ws: Workspace, state: UiState, events: list[UiEvent]):
    if ws.assistants or ws.interview.answered * 2 < ws.interview.total:
        return None
    return 8, Hint(id="first-assistant", tone="suggestion", title="Create your first assistant",
                   body="The partner knows enough about the business to draft an assistant for a role.",
                   action=HintAction(label="Ask the partner", href="/partner"))


RULES: list[Rule] = [repeated_error, idle, connector_status, approvals, drafts, interview, unorganized, recommended,
                     first_assistant]


def _section(path: str) -> str:
    return "/" + path.split("?")[0].strip("/").split("/")[0]


def hints(ws: Workspace, state: UiState, events: list[UiEvent]) -> list[Hint]:
    ranked = []
    for order, rule in enumerate(RULES):
        found = rule(ws, state, events)
        if found is None:
            continue
        priority, hint = found
        if hint.action and hint.action.href == state.page:
            hint.action = None
        elif hint.action and _section(hint.action.href) == _section(state.page) != "/":
            priority -= 5
        ranked.append((priority, order, hint))
    return [hint for *_, hint in sorted(ranked, key=lambda r: r[:2])][:MAX_HINTS]
