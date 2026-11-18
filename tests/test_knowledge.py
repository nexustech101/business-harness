"""The knowledge index: workspace memory in the vector index, search breadth, the browsable map and its tools."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import agent
from business import memory
from business.schema import (
    AnswerRequest,
    AssistantSpec,
    BusinessProfile,
    Department,
    KnowledgeSearchRequest,
    NoteCreate,
    OrganizeRequest,
    Role,
    RunRequest,
)
from library.ingest import ChunkDraft
from library.schema import DocumentFilters, SearchFilters
from library.search import diversify
from tests.conftest import make_test_app
from tests.fakes import Chat, Embeddings, add, config, draft, openai_answer, openai_tool_call, workspace
from tests.test_assistant import run_tool
from tests.test_assistants import ask, tool_results

BAKERY = BusinessProfile(
    name="Keystone Bakery", summary="Artisan bread for cafes.", offerings=["Sourdough", "Catering"],
    departments=[Department(name="Finance", purpose="Books and payroll", responsibilities=["Month-end close"])],
    roles=[Role(title="Bookkeeper", department="Finance", duties=["Reconcile the Stripe payouts weekly"])])


def long_draft(title: str, passages: list[str]):
    """A document with one chunk per passage."""
    d = draft(passages[0], title=title)
    d.chunks = [ChunkDraft(content=text, section_title=f"Part {i + 1}")
                for i, text in enumerate(passages)]
    return d


def sync(business, owner: str = "1") -> int:
    return asyncio.run(memory.sync(business, owner))


def sources(business, owner: str = "1", **kwargs):
    return asyncio.run(business.knowledge(owner, DocumentFilters(**kwargs.pop("filters", {})), 50, 0,
                                          kwargs.pop("unused_only", False)))


# --- workspace memory ---------------------------------------------------------------------------------


def test_profile_answers_and_notes_become_searchable_records(tmp_path):
    business, _ = workspace(tmp_path)
    assert sync(business) == 0 and sources(business).sources == 0  # an empty workspace remembers nothing
    business.save_profile("1", BAKERY)
    business.answer("1", AnswerRequest(question_id="operations.suppliers", answer="Flour from Millstone Co-op."))
    business.post_note("1", NoteCreate(topic="Finance", text="Payroll runs on the 25th."))
    assert sync(business) == 3
    found = sources(business)
    assert {(s.title, s.origin) for s in found.items} == {
        ("Business profile", "workspace"), ("Discovery answers", "workspace"), ("Shared notes", "workspace")}
    profile = next(s for s in found.items if s.title == "Business profile")
    assert profile.sections == ["Overview", "Products and services", "Department: Finance", "Role: Bookkeeper"]
    hits = asyncio.run(business.search("1", KnowledgeSearchRequest(query="reconcile Stripe payouts weekly"))).hits
    assert (hits[0].title, hits[0].section_title) == ("Business profile", "Role: Bookkeeper")
    hits = asyncio.run(business.search("1", KnowledgeSearchRequest(query="Millstone flour supplier"))).hits
    assert (hits[0].title, hits[0].section_title) == ("Discovery answers", "Operations and delivery")
    assert asyncio.run(business.search("2", KnowledgeSearchRequest(query="Stripe payouts"))).hits == []


def test_sync_rewrites_only_what_changed_and_removes_what_is_gone(tmp_path):
    business, _ = workspace(tmp_path)
    business.save_profile("1", BAKERY)
    assert (sync(business), sync(business)) == (1, 0)  # unchanged text: nothing embedded again
    embedded = len(business.library.embedder.transport.inputs)
    business.save_profile("1", BAKERY.model_copy(update={"summary": "Artisan bread and pastry for cafes."}))
    assert sync(business) == 1 and len(business.library.embedder.transport.inputs) > embedded
    assert sources(business).sources == 1  # the old record was replaced, not kept beside the new one
    hit = asyncio.run(business.search("1", KnowledgeSearchRequest(query="pastry"))).hits[0]
    assert "pastry" in hit.content
    business.save_profile("1", BusinessProfile())
    assert sync(business) == 1 and sources(business).sources == 0


def test_workspace_records_are_not_counted_as_uploads(tmp_path):
    business, _ = workspace(tmp_path)
    business.save_profile("1", BAKERY)
    add(business.library, draft("lease terms", title="lease"), owner="1")
    sync(business)
    summary = business.summary("1")
    assert (summary.documents, summary.organized_documents) == (1, 0)
    assert business.library.list(DocumentFilters(origin="upload"), "1")[0] == 1
    assert business.library.list(DocumentFilters(origin="workspace"), "1")[0] == 1
    assert business.library.list(DocumentFilters(), "1")[0] == 2


# --- search breadth ---------------------------------------------------------------------------------


def test_diversify_caps_one_document_and_fills_from_the_rest():
    documents = {1: "a", 2: "a", 3: "a", 4: "a", 5: "b", 6: "c"}
    assert diversify([1, 2, 3, 4, 5, 6], documents, limit=4) == [1, 2, 5, 6]  # at most half from one document
    assert diversify([1, 2, 3, 4], documents, limit=4) == [1, 2, 3, 4]  # nothing else matched: held ones fill up
    assert diversify([5, 1], documents, limit=8) == [5, 1]


def test_a_long_document_does_not_crowd_out_a_short_one(tmp_path):
    business, _ = workspace(tmp_path)
    add(business.library, long_draft("handbook", [f"refund policy clause {i} refund policy" for i in range(12)]))
    memo = add(business.library, draft("refund exceptions for wholesale", title="memo"))
    found = asyncio.run(business.library.search_wide("refund policy", SearchFilters(), "1", limit=4))
    assert [hit.title for hit in found.hits].count("handbook") == 3  # 12 clauses matched; the memo still shows
    assert memo.id in {hit.document_id for hit in found.hits} and found.other_sources == []
    one = asyncio.run(business.library.search_wide("refund policy", SearchFilters(), "1", limit=1))
    assert [hit.title for hit in one.hits] == ["handbook"] and [s.title for s in one.other_sources] == ["memo"]


# --- the browsable index ----------------------------------------------------------------------------


def test_the_map_shows_every_source_and_what_was_never_retrieved(tmp_path):
    business, _ = workspace(tmp_path)
    handbook = add(business.library, long_draft("handbook", ["onboarding steps", "holiday schedule", "dress code"]))
    lease = add(business.library, draft("warehouse lease renewal in 2031", title="lease"))
    business.organize("1", lease.id, OrganizeRequest(department="Operations", kind="contract"))
    before = sources(business)
    assert (before.sources, before.passages, before.never_retrieved) == (2, 4, 4)
    asyncio.run(business.search("1", KnowledgeSearchRequest(query="holiday schedule", limit=1)))
    after = sources(business)
    assert (after.passages, after.never_retrieved) == (4, 3)
    by_title = {s.title: s for s in after.items}
    assert (by_title["handbook"].never_retrieved, by_title["handbook"].sections) == (2, ["Part 1", "Part 2", "Part 3"])
    assert by_title["handbook"].last_retrieved_at is not None and by_title["lease"].last_retrieved_at is None
    assert (by_title["lease"].kind, by_title["lease"].department, by_title["lease"].origin) == (
        "contract", "Operations", "upload")
    unused = sources(business, unused_only=True)
    assert [s.title for s in unused.items] == ["handbook", "lease"] and unused.count == 2  # most unread first
    assert [s.title for s in sources(business, filters={"q": "leas"}).items] == ["lease"]
    read = business.passages("1", handbook.id, 2, 1)
    assert (read.count, [p.index for p in read.passages], [p.retrievals for p in read.passages]) == (3, [1, 2], [1, 0])
    assert business.passages("2", handbook.id, 2, 0) is None and sources(business, owner="2").sources == 0


def test_browse_and_read_tools_reach_what_search_did_not_return(tmp_path):
    business, _ = workspace(tmp_path)
    handbook = add(business.library, long_draft("handbook", ["onboarding steps", "holiday schedule", "dress code"]))
    add(business.library, draft("warehouse lease", title="lease"))
    listed = run_tool("browse_knowledge", {}, business.library)
    assert listed.startswith("2 source(s), 4 passage(s), 4 never retrieved. 2 match; showing 1-2:")
    assert f"- {handbook.id} | handbook | txt file | 3 passage(s), 3 never retrieved | sections: Part 1; Part 2; Part 3" \
        in listed
    first = run_tool("read_document", {"document_id": handbook.id, "limit": 2}, business.library)
    assert first.startswith("handbook: passages 1-2 of 3.") and "[1] handbook" in first and "[2] handbook" in first
    assert first.endswith("1 more passage(s): call read_document with offset 2.")
    assert "dress code" in run_tool("read_document", {"document_id": handbook.id, "offset": 2}, business.library)
    unused = run_tool("browse_knowledge", {"unused_only": True}, business.library)
    assert "handbook" not in unused and "lease" in unused  # every handbook passage has been read now
    assert run_tool("read_document", {"document_id": handbook.id}, business.library, owner="2").startswith("error:")
    scoped = run_tool("browse_knowledge", {}, business.library, scope=SearchFilters(document_ids=[handbook.id]))
    assert scoped.startswith("1 source(s), 3 passage(s)") and "lease" not in scoped


def test_search_names_the_sources_it_did_not_show(tmp_path):
    business, _ = workspace(tmp_path)
    for n in range(3):
        add(business.library, draft(f"supplier contract {n} renewal terms", title=f"contract-{n}"))
    result = run_tool("search_documents", {"query": "supplier contract renewal", "limit": 1}, business.library)
    assert result.count("[document ") == 3 and "Also relevant, not shown (open with read_document):" in result
    nothing = run_tool("search_documents", {"query": "zzz"}, business.library, scope=SearchFilters(document_ids=["none"]))
    assert nothing == "No matching documents. browse_knowledge lists everything that is stored."


def test_assistants_search_workspace_records_whatever_their_document_scope(tmp_path):
    business, chat = workspace(tmp_path, [openai_tool_call({"query": "Stripe payouts"}), openai_answer("Weekly.")])
    business.save_profile("1", BAKERY)
    info = business.create_assistant("1", AssistantSpec(name="Clerk", role="Files", knowledge={"document_kinds": ["x"]}))
    business.set_status("1", info.id, "active")
    asyncio.run(business.run("1", info.id, RunRequest(messages=ask("How often are payouts reconciled?"))))
    assert "Reconcile the Stripe payouts weekly" in tool_results(chat)[0]


# --- routes -------------------------------------------------------------------------------------------


def test_knowledge_routes(tmp_path):
    app, key = make_test_app(assistant=agent.build(config(tmp_path), Chat([]), Embeddings()))
    business = app.state.business
    with TestClient(app) as client:
        client.headers["X-API-Key"] = key
        owner = str(client.get("/auth/me").json()["data"]["id"])
        business.save_profile(owner, BAKERY)
        handbook = add(business.library, long_draft("handbook", ["onboarding steps", "holiday schedule"]), owner=owner)
        whole = client.get("/v1/knowledge").json()["data"]
        assert (whole["sources"], whole["passages"], whole["never_retrieved"], whole["count"]) == (2, 6, 6, 2)
        assert {i["origin"] for i in whole["items"]} == {"upload", "workspace"}
        assert [i["title"] for i in client.get("/v1/knowledge?origin=upload").json()["data"]["items"]] == ["handbook"]
        found = client.post("/v1/knowledge/search", json={"query": "holiday schedule", "limit": 1}).json()["data"]
        assert found["hits"][0]["title"] == "handbook" and found["other_sources"] == []
        assert client.get("/v1/knowledge?unused=true").json()["data"]["never_retrieved"] == 5
        passages = client.get(f"/v1/knowledge/{handbook.id}/passages").json()["data"]
        assert [p["retrievals"] for p in passages["passages"]] == [0, 1] and passages["title"] == "handbook"
        assert client.get("/v1/knowledge/nope/passages").status_code == 404
        listed = client.get("/v1/library/documents").json()["data"]
        assert [d["title"] for d in listed["documents"]] == ["handbook"]  # uploads only, by default
        for data, name in (({"location": "workspace://profile"}, "a.txt"), ({}, "workspace://profile")):
            refused = client.post("/v1/library/documents", data=data, files={"file": (name, b"x", "text/plain")})
            assert refused.status_code == 400  # neither the location nor the file name may claim the prefix
