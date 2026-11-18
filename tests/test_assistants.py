"""The business partner's tool loop, role assistants (context, tools, write policy), approvals, and the routes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agent
from agent.schema import ChatMessage
from agent.tools import MAX_CHARS, Tool
from business.connectors import ToolResult
from business.errors import AlreadyDecided, NotActive
from business.partner import PARTNER_TOOLS
from business.runner import exposed_name
from business.schema import (
    ApprovalDecision,
    AssistantSpec,
    BusinessProfile,
    OrganizeRequest,
    PartnerRequest,
    RunRequest,
    ToolInUse,
    UiEntity,
    UiState,
)
from business.service import Business
from tests.conftest import make_test_app
from tests.fakes import (
    Chat,
    Embeddings,
    FakeHub,
    add,
    config,
    connector,
    connector_tool,
    draft,
    fake_parser,
    listing,
    openai_answer,
    openai_tool_call,
    openai_turn,
    workspace,
)


def ask(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


def tool_results(chat: Chat) -> list[str]:
    """The tool messages of the last request, in order."""
    return [m["content"] for m in chat.requests[-1]["messages"] if m["role"] == "tool"]


# --- partner ----------------------------------------------------------------------------------------------


def test_partner_interviews_records_and_drafts_an_assistant(tmp_path):
    hub = FakeHub(catalog=[listing("quickbooks", "QuickBooks Online", "Accounting")],
                  installed={"1": [connector("qb", "QuickBooks", listing_id="quickbooks")]})
    business, chat = workspace(tmp_path, [
        openai_tool_call({}, name="next_questions"),
        openai_turn(None, ("record_answer", {"question_id": "identity.name", "answer": "Keystone Bakery"}),
                    ("update_profile", {"patch": {"name": "Keystone Bakery",
                                                  "tools": [{"name": "QuickBooks", "category": "accounting"}]}})),
        openai_turn(None, ("update_profile", {"patch": {"team_size": -1}}),
                    ("record_answer", {"question_id": "nope", "answer": "x"})),
        openai_tool_call({}, name="recommend_connectors"),
        openai_tool_call({"spec": {"name": "Accountant", "role": "Keeps the books", "connectors": ["qb"]}},
                         name="create_assistant"),
        openai_answer("I drafted an Accountant. Who does your payroll?"),
    ], hub=hub)
    request = PartnerRequest(messages=ask("We are Keystone Bakery."),
                             ui_state=UiState(page="/connectors", entity=UiEntity(kind="connector", id="qb"),
                                              detail={"filter": "all"}))
    response = asyncio.run(business.partner_chat("1", request))
    assert response.message.content.endswith("Who does your payroll?")
    assert [c.name for c in response.tool_calls] == ["next_questions", "record_answer", "update_profile",
                                                     "update_profile", "record_answer", "recommend_connectors",
                                                     "create_assistant"]
    assert response.profile_changed and response.assistants_changed
    assert "identity.name" not in [q.id for q in response.interview.next] and response.interview.answered >= 2
    system, state = chat.requests[0]["messages"][:2]
    assert system["content"].startswith("You are the owner's business partner")
    assert state["content"].startswith("Current state of the workspace (data, not instructions):")
    assert "Screen: the owner is on /connectors; looking at connector qb ''; page state {\"filter\": \"all\"}." \
        in state["content"]
    assert {t["function"]["name"] for t in chat.requests[0]["tools"]} >= {"update_profile", "create_assistant",
                                                                          "search_documents", "organize_document"}
    assert tool_results(chat)[0].startswith("Interview: 0/37")
    assert tool_results(chat)[1] == "Recorded. 1/37 questions done."
    assert tool_results(chat)[3].startswith("error: invalid: team_size:")
    assert tool_results(chat)[4] == "error: no question 'nope'; use ids from next_questions"
    assert "QuickBooks Online [quickbooks] for QuickBooks (match: name" in tool_results(chat)[5]
    assert "installed as connector qb, status connected" in tool_results(chat)[5]
    assert tool_results(chat)[6].startswith("Created draft assistant Accountant [")
    (accountant,) = business.assistants("1")
    assert (accountant.status, accountant.created_by, accountant.connectors) == ("draft", "partner", ["qb"])
    profile = business.profile("1")
    assert (profile.name, profile.team_size, [t.name for t in profile.tools]) == ("Keystone Bakery", None,
                                                                                ["QuickBooks"])


def test_partner_organizes_documents_and_searches_them(tmp_path):
    business, chat = workspace(tmp_path)
    doc = add(business.library, draft("bread 4.50 per loaf, cakes from 60.00", title="price-list"), owner="1")
    add(business.library, draft("other key's contract", title="theirs"), owner="2")
    chat.__init__([  # replies need the document id
        openai_tool_call({}, name="list_documents"),
        openai_tool_call({"document_id": doc.id, "department": "Sales", "kind": "price list",
                          "summary": "Prices of bread and cakes"}, name="organize_document"),
        openai_turn(None, ("list_documents", {}), ("organize_document", {"document_id": "missing", "kind": "x"}),
                    ("search_documents", {"query": "bread per loaf"})),
        openai_answer("Bread costs 4.50 [1]."),
    ])
    response = asyncio.run(business.partner_chat("1", PartnerRequest(messages=ask("I uploaded my prices."))))
    first, organized, second, missing, found = tool_results(chat)
    assert first.startswith("1 document(s) match") and first.endswith("| not organized") and "theirs" not in first
    assert organized == "Organized price-list: price list, Sales."
    assert second.endswith("| organized: price list, Sales") and missing == "error: no document missing"
    assert found.startswith("[1] price-list") and [s.title for s in response.sources] == ["price-list"]
    assert not response.profile_changed and [d.kind for d in business.documents("1")] == ["price list"]


def test_partner_changes_to_an_active_assistant_return_it_to_draft(tmp_path):
    business, chat = workspace(tmp_path)
    active = business.create_assistant("1", AssistantSpec(name="Marketer", role="Posts"))
    business.set_status("1", active.id, "active")
    chat.__init__([openai_tool_call({"assistant_id": active.id, "spec": {"name": "Marketer", "role": "Posts daily",
                                                                          "policy": {"default": "auto"}}},
                                    name="update_assistant"),
                   openai_tool_call({"assistant_id": active.id, "spec": {"name": "Marketer", "role": "x",
                                                                          "connectors": ["nope"]}},
                                    name="update_assistant"),
                   openai_answer("Updated.")])
    business.set_status = lambda *a: pytest.fail("the status must be written with the spec, not after it")
    response = asyncio.run(business.partner_chat("1", PartnerRequest(messages=ask("Make it post daily."))))
    assert response.assistants_changed and tool_results(chat)[1] == "error: Connector(s) not installed: nope."
    updated = business.assistant("1", active.id)
    assert (updated.role, updated.status, updated.policy.default) == ("Posts daily", "draft", "auto")


def test_partner_tool_results_are_capped(tmp_path, monkeypatch):
    async def huge(args, ctx):
        return "x" * (MAX_CHARS + 500)

    monkeypatch.setitem(PARTNER_TOOLS, "next_questions", Tool("next_questions", "d", {"type": "object"}, huge))
    business, chat = workspace(tmp_path, [openai_tool_call({}, name="next_questions"), openai_answer("ok")])
    asyncio.run(business.partner_chat("1", PartnerRequest(messages=ask("hi"))))
    assert tool_results(chat) == ["x" * MAX_CHARS + "\n[truncated]"]


# --- role assistants -----------------------------------------------------------------------------------------


def books_hub(results=None) -> FakeHub:
    return FakeHub(installed={"1": [connector("qb", "QuickBooks"), connector("gm", "Gmail"),
                                    connector("off", "Offline", status="error")]},
                   tools=[connector_tool("qb", "list_invoices", True), connector_tool("qb", "create_invoice", False),
                          connector_tool("qb", "delete_invoice", False), connector_tool("qb", "void_invoice", False),
                          connector_tool("gm", "send_email", False), connector_tool("off", "anything", True)],
                   results=results)


def accountant(business, status="active", **spec):
    base = {"name": "Accountant", "role": "Keeps the books", "department": "Finance", "connectors": ["qb", "off"],
            "shares": ["finance"],
            "policy": {"default": "ask", "tools": {"qb/delete_invoice": "deny", "qb/void_invoice": "auto"}}}
    info = business.create_assistant("1", AssistantSpec(**{**base, **spec}))
    return business.set_status("1", info.id, status)


def test_run_applies_the_write_policy_and_records_every_call(tmp_path):
    business, chat = workspace(tmp_path, [
        openai_turn("I'll check the open invoices, then bill Café Rosa.", ("qb__list_invoices", {}),
                    ("qb__create_invoice", {"id": "rosa"})),
        openai_turn(None, ("qb__delete_invoice", {"id": "7"}), ("qb__void_invoice", {"id": "8"})),
        openai_turn(None, ("gm__send_email", {"id": "x"}), ("post_note", {"topic": "finance", "text": "Billed Rosa."}),
                    ("post_note", {"topic": "sales", "text": "not mine"})),
        openai_answer("Invoice for Café Rosa awaits your approval."),
    ], hub=books_hub())
    info = accountant(business)
    response = asyncio.run(business.run("1", info.id, RunRequest(messages=ask("Bill Café Rosa."))))
    assert response.message.content == "Invoice for Café Rosa awaits your approval."
    outcomes = [(r.connector_id, r.tool, r.read_only, r.outcome) for r in response.tool_runs]
    assert outcomes == [("qb", "list_invoices", True, "ran"), ("qb", "create_invoice", False, "pending_approval"),
                        ("qb", "delete_invoice", False, "denied"), ("qb", "void_invoice", False, "ran"),
                        (None, "gm__send_email", False, "failed"), (None, "post_note", False, "ran"),
                        (None, "post_note", False, "failed")]
    assert [c[2] for c in business.hub.calls] == ["list_invoices", "void_invoice"]  # nothing else reached the hub
    offered = {t["function"]["name"] for t in chat.requests[0]["tools"]}
    assert offered == {"search_documents", "browse_knowledge", "read_document", "read_notes", "post_note",
                       "qb__list_invoices", "qb__create_invoice", "qb__delete_invoice",
                       "qb__void_invoice"}  # no Gmail (not in the spec), no failing connector
    assert [m["role"] for m in chat.requests[0]["messages"]] == ["system"] * 3 + ["user", "user"]  # notes: data
    (approval,) = business.approvals("1", "pending")
    assert (approval.tool, approval.arguments, approval.assistant_name) == ("create_invoice", {"id": "rosa"},
                                                                            "Accountant")
    assert approval.reason == "I'll check the open invoices, then bill Café Rosa."
    assert response.tool_runs[1].approval_id == approval.id and "queued for the owner's approval" in \
        response.tool_runs[1].result
    assert response.tool_runs[2].result.startswith("refused: Accountant may not run qb/delete_invoice")
    assert [n.text for n in business.notes("1", "finance")] == ["Billed Rosa."]
    assert business.notes("1", "finance")[0].author == "Accountant"


def test_only_active_assistants_run(tmp_path):
    business, _ = workspace(tmp_path, hub=books_hub())
    info = accountant(business, status="paused")
    with pytest.raises(NotActive, match="paused"):
        asyncio.run(business.run("1", info.id, RunRequest(messages=ask("x"))))
    assert asyncio.run(business.run("2", info.id, RunRequest(messages=ask("x")))) is None


def test_context_preview_matches_what_a_run_sends(tmp_path):
    business, chat = workspace(tmp_path, [openai_answer("ok")], hub=books_hub())
    business.save_profile("1", BusinessProfile(name="Keystone Bakery", tools=[ToolInUse(name="QuickBooks")]))
    info = accountant(business)
    business.create_assistant("1", AssistantSpec(name="Marketer", role="Posts", shares=["finance"]))
    context = asyncio.run(business.context("1", info.id))
    assert context.tools == ["search_documents", "browse_knowledge", "read_document", "read_notes", "post_note",
                             "qb/list_invoices", "qb/create_invoice", "qb/delete_invoice", "qb/void_invoice"]
    assert "Marketer" not in context.layers[2].text  # drafts are not on the team
    asyncio.run(business.run("1", info.id, RunRequest(messages=ask("hi"))))
    sent = chat.requests[0]["messages"][:4]
    assert [m["content"] for m in sent] == [layer.text for layer in context.layers]
    assert [m["role"] for m in sent] == ["system", "system", "system", "user"]  # notes are data, not instructions
    assert asyncio.run(business.context("2", info.id)) is None


def test_search_is_limited_to_the_knowledge_scope(tmp_path):
    business, chat = workspace(tmp_path, [openai_tool_call({"query": "invoice terms"}), openai_answer("a"),
                                          openai_tool_call({"query": "invoice terms"}), openai_answer("b")])
    finance = add(business.library, draft("invoice terms net 30", title="finance-terms"), owner="1")
    sales = add(business.library, draft("invoice terms for quotes", title="sales-terms"), owner="1")
    add(business.library, draft("invoice terms unorganized", title="loose"), owner="1")
    business.organize("1", finance.id, OrganizeRequest(department="Finance", kind="policy"))
    business.organize("1", sales.id, OrganizeRequest(department="Sales", kind="policy"))
    info = accountant(business, connectors=[], policy={}, knowledge={"departments": ["finance"]})
    asyncio.run(business.run("1", info.id, RunRequest(messages=ask("Terms?"))))
    assert "finance-terms" in tool_results(chat)[0] and "sales-terms" not in tool_results(chat)[0]
    assert "loose" not in tool_results(chat)[0]
    other = accountant(business, name="Clerk", connectors=[], policy={}, knowledge={"document_kinds": ["contract"]})
    asyncio.run(business.run("1", other.id, RunRequest(messages=ask("Terms?"))))
    assert tool_results(chat) == ["No documents are in this assistant's knowledge scope."]


def test_connector_tool_names_follow_the_provider_rules():
    taken = {"search_documents"}
    assert exposed_name("qb", "list_invoices", taken) == "qb__list_invoices"
    assert exposed_name("my conn.1", "list/all", taken) == "my_conn_1__list_all"
    long = exposed_name("c" * 40, "t" * 40, taken)
    assert len(long) == 64 and long != exposed_name("c" * 40, "t" * 41, taken)
    assert exposed_name("qb", "x", {"qb__x"}) != "qb__x"
    fallback = exposed_name("qb", "x", {"qb__x"})
    salted = exposed_name("qb", "x", {"qb__x", fallback})  # the hashed name is taken too: salt until free
    assert salted not in {"qb__x", fallback} and len(salted) <= 64


# --- approvals ----------------------------------------------------------------------------------------------


def queued(tmp_path, results=None):
    business, _ = workspace(tmp_path, [openai_turn("Billing.", ("qb__create_invoice", {"id": "a"}),
                                                   ("qb__create_invoice", {"id": "b"}),
                                                   ("qb__create_invoice", {"id": "c"})),
                                       openai_answer("Queued.")], hub=books_hub(results))
    info = accountant(business)
    asyncio.run(business.run("1", info.id, RunRequest(messages=ask("Bill them."))))
    return business, info, {a.arguments["id"]: a for a in business.approvals("1", "pending")}


def test_approve_runs_the_call_reject_records_and_always_sets_auto(tmp_path):
    business, info, pending = queued(tmp_path)
    done = asyncio.run(business.decide("1", pending["a"].id, ApprovalDecision(approve=True, always=True), "owner"))
    assert (done.status, done.result, done.decided_by) == ("executed", "create_invoice done", "owner")
    assert business.hub.calls == [("1", "qb", "create_invoice", {"id": "a"})]
    assert business.assistant("1", info.id).policy.tools["qb/create_invoice"] == "auto"
    rejected = asyncio.run(business.decide("1", pending["b"].id, ApprovalDecision(approve=False, note="no"), "owner"))
    assert (rejected.status, rejected.note, rejected.result) == ("rejected", "no", None)
    assert len(business.hub.calls) == 1
    with pytest.raises(AlreadyDecided, match="already executed"):
        asyncio.run(business.decide("1", pending["a"].id, ApprovalDecision(approve=True), "owner"))
    assert asyncio.run(business.decide("2", pending["c"].id, ApprovalDecision(approve=True), "x")) is None
    assert [a.status for a in business.approvals("1", None)].count("pending") == 1


def test_a_failing_call_is_recorded_as_failed_and_always_does_not_apply(tmp_path):
    business, info, pending = queued(tmp_path, {"create_invoice": ToolResult("customer not found", is_error=True)})
    failed = asyncio.run(business.decide("1", pending["a"].id, ApprovalDecision(approve=True, always=True), "owner"))
    assert (failed.status, failed.result) == ("failed", "customer not found")
    assert "qb/create_invoice" not in business.assistant("1", info.id).policy.tools


def test_always_skips_a_connector_the_assistant_no_longer_has(tmp_path):
    business, info, pending = queued(tmp_path)
    spec = AssistantSpec.model_validate(info.model_dump(include=set(AssistantSpec.model_fields)) |
                                        {"connectors": ["off"], "policy": {}})
    business.update_assistant("1", info.id, spec)
    done = asyncio.run(business.decide("1", pending["a"].id, ApprovalDecision(approve=True, always=True), "owner"))
    assert done.status == "executed" and business.assistant("1", info.id).policy.tools == {}


def test_an_approval_is_claimed_before_its_call_runs(tmp_path):
    business, _, pending = queued(tmp_path)
    other = Business(business.config, business.library, business.chat, business.hub)  # another process, same file
    seen = []

    async def call(owner, connector_id, tool, arguments):
        seen.append(business.store.approval(owner, pending["a"].id).status)
        with pytest.raises(AlreadyDecided, match="already executing"):
            await other.decide("1", pending["a"].id, ApprovalDecision(approve=True), "o")
        return ToolResult("done")

    business.hub.call = call
    done = asyncio.run(business.decide("1", pending["a"].id, ApprovalDecision(approve=True), "owner"))
    assert seen == ["executing"] and done.status == "executed"


def test_concurrent_decisions_run_the_call_once(tmp_path):
    business, _, pending = queued(tmp_path)

    async def both():
        decision = ApprovalDecision(approve=True)
        return await asyncio.gather(business.decide("1", pending["a"].id, decision, "o"),
                                    business.decide("1", pending["a"].id, decision, "o"), return_exceptions=True)

    results = asyncio.run(both())
    assert sorted(type(r).__name__ for r in results) == ["AlreadyDecided", "Approval"]
    assert len(business.hub.calls) == 1


# --- HTTP ------------------------------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    chat = Chat([openai_tool_call({"question_id": "identity.name", "answer": "Keystone"}, name="record_answer"),
                 openai_answer("Noted. What do you sell?"),
                 openai_turn("Creating the invoice.", ("qb__create_invoice", {"id": "a"})),
                 openai_answer("It awaits your approval.")])
    built = agent.build(config(tmp_path), chat, Embeddings())
    hub = books_hub()
    app, admin = make_test_app(parser=fake_parser(), assistant=built,
                               connectors=hub)
    with TestClient(app) as client:
        created = [client.post("/api-keys", json={"name": n}, headers={"X-API-Key": admin}).json()["data"]
                   for n in ("firm", "other")]
        hub.installed = {str(created[0]["api_key"]["id"]): hub.installed["1"]}
        yield SimpleNamespace(client=client, key={"X-API-Key": created[0]["key"]},
                              other={"X-API-Key": created[1]["key"]})


def test_workspace_routes_end_to_end_and_owner_isolation(api):
    c, key, other = api.client, api.key, api.other
    assert c.get("/v1/workspace", headers=key).json()["data"]["interview"]["answered"] == 0
    r = c.put("/v1/business/profile", json={"name": "Keystone Bakery", "summary": "Bakery"}, headers=key)
    assert r.status_code == 200 and r.json()["data"]["updated_at"]
    assert c.put("/v1/business/profile", json={"name": "x", "unknown": 1}, headers=key).status_code == 422
    r = c.post("/v1/business/interview/answers", json={"question_id": "finance.method", "answer": "cash"}, headers=key)
    assert r.status_code == 200 and r.json()["data"]["answered"] == 3
    assert c.post("/v1/business/interview/answers", json={"question_id": "x", "answer": "y"},
                  headers=key).status_code == 404

    r = c.post("/v1/partner/chat", json={"messages": [{"role": "user", "content": "We are Keystone."}],
                                         "ui_state": {"page": "/partner"}}, headers=key)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["tool_calls"][0]["name"] == "record_answer" and not r.json()["data"]["profile_changed"]

    doc = c.post("/v1/library/documents", files={"file": ("prices.md", b"# Prices\nBread 4.50", "text/markdown")},
                 headers=key).json()["data"]
    assert c.put(f"/v1/business/documents/{doc['id']}", json={"kind": "price list"}, headers=other).status_code == 404
    assert c.put(f"/v1/business/documents/{doc['id']}", json={"kind": "price list", "department": "Sales"},
                 headers=key).status_code == 200
    assert [d["kind"] for d in c.get("/v1/business/documents", headers=key).json()["data"]] == ["price list"]

    spec = {"name": "Accountant", "role": "Keeps the books", "connectors": ["qb"], "shares": ["finance"]}
    assert c.post("/v1/assistants", json=spec, headers=other).json()["error"]["code"] == "invalid_assistant"
    r = c.post("/v1/assistants", json=spec, headers=key)
    assert r.status_code == 201 and r.json()["data"]["status"] == "draft"
    assistant_id = r.json()["data"]["id"]
    assert c.post(f"/v1/assistants/{assistant_id}/run", json={"messages": [{"role": "user", "content": "go"}]},
                  headers=key).json()["error"]["code"] == "assistant_inactive"
    assert c.put(f"/v1/assistants/{assistant_id}/status", json={"status": "active"}, headers=key).status_code == 200
    context = c.get(f"/v1/assistants/{assistant_id}/context", headers=key).json()["data"]
    assert [layer["name"] for layer in context["layers"]] == ["business", "role", "team", "notes"]
    r = c.post(f"/v1/assistants/{assistant_id}/run", json={"messages": [{"role": "user", "content": "Bill a"}]},
               headers=key)
    assert r.status_code == 200, r.text
    assert [t["outcome"] for t in r.json()["data"]["tool_runs"]] == ["pending_approval"]

    (approval,) = c.get("/v1/approvals", params={"status": "pending"}, headers=key).json()["data"]
    assert c.get("/v1/approvals", headers=other).json()["data"] == []
    assert c.post(f"/v1/approvals/{approval['id']}/decision", json={"approve": True}, headers=other).status_code == 404
    r = c.post(f"/v1/approvals/{approval['id']}/decision", json={"approve": True}, headers=key)
    assert r.json()["data"]["status"] == "executed" and r.json()["data"]["decided_by"] == "firm"
    r = c.post(f"/v1/approvals/{approval['id']}/decision", json={"approve": False}, headers=key)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_decided"

    assert c.post("/v1/business/notes", json={"topic": "finance", "text": "Month-end on the 3rd"},
                  headers=key).status_code == 201
    assert [n["author"] for n in c.get("/v1/business/notes", params={"topic": "finance"}, headers=key).json()["data"]] \
        == ["owner"]
    hints = c.post("/v1/workspace/hints", json={"state": {"page": "/"}, "events": []}, headers=key).json()["data"]
    assert [h["id"] for h in hints["hints"]] == ["connector-status:off", "interview"]

    for path in ("/v1/business/notes", "/v1/assistants", "/v1/business/documents"):
        assert c.get(path, headers=other).json()["data"] == [], path
    theirs = c.get("/v1/workspace", headers=other).json()["data"]
    assert (theirs["business_name"], theirs["documents"], theirs["interview"]["answered"]) == ("", 0, 0)
    assert c.get(f"/v1/assistants/{assistant_id}", headers=other).status_code == 404
    assert c.get("/v1/business/profile", headers=other).json()["data"]["name"] == ""
    assert c.get("/v1/assistants/schema", headers=key).json()["data"]["title"] == "AssistantSpec"
    assert c.delete(f"/v1/assistants/{assistant_id}", headers=other).status_code == 404
    assert c.delete(f"/v1/assistants/{assistant_id}", headers=key).status_code == 204
