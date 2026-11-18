"""Document library and assistant, with the model providers replaced by httpx.MockTransport (tests/fakes.py)."""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import agent
from agent.agent import ChatClient, _anthropic_request
from agent.config import load_config
from agent.schema import ChatMessage, ChatRequest
from core.config import PROJECT_ROOT
from core.parser import UnsupportedDocument
from core.utils import mask_ssns
from library.ingest import file_type, read_file
from library.schema import DocumentFilters, SearchFilters
from library.search import Embedder
from library.service import Library
from library.store import IndexMismatch
from tests.conftest import make_test_app
from tests.fakes import (
    Chat,
    Embeddings,
    add,
    blank_pdf,
    config,
    draft,
    fake_parser,
    fake_vector,
    openai_answer,
    openai_tool_call,
    search,
)


@pytest.fixture
def library(tmp_path):
    return Library(config(tmp_path).library, Embedder(config(tmp_path).embeddings, Embeddings()))


def ask(text: str) -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role="user", content=text)])


# --- config ---------------------------------------------------------------------------------


def test_shipped_config_is_valid_and_local(monkeypatch):
    c = load_config(PROJECT_ROOT / "config" / "model_config.yml")
    assert (c.chat.provider, c.embeddings.provider) == ("ollama", "ollama")
    assert c.chat.url == "http://localhost:11434/v1" and c.chat.api_key() is None
    assert c.library.database.is_absolute()
    keyed = c.chat.model_copy(update={"api_key_env": "TEST_LLM_KEY"})
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(KeyError, match="TEST_LLM_KEY"):
        keyed.api_key()
    monkeypatch.setenv("TEST_LLM_KEY", "sk-test")
    assert keyed.api_key() == "sk-test"


# --- ingest ---------------------------------------------------------------------------------


def test_text_files_are_chunked_by_their_structure():
    md = "# Engagement\nWe bake to order.\n\n## Fees\nFlat fee per order.\n" + "More fee detail. " * 200
    draft_ = asyncio.run(read_file(None, md.encode(), "letter.md", chunk_chars=500))
    assert [c.section_title for c in draft_.chunks][:2] == ["Engagement", "Fees"]
    assert all(len(c.content) <= 500 for c in draft_.chunks) and draft_.chunks[1].header_level == 2
    rows = "name,amount\n" + "".join(f"item {i},{i}.00\n" for i in range(200))
    csv_chunks = asyncio.run(read_file(None, rows.encode(), "ledger.csv", chunk_chars=400)).chunks
    assert len(csv_chunks) > 1 and all(c.content.startswith("name, amount") for c in csv_chunks)


def test_xlsx_rows_keep_their_sheet():
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Staff"
    book.active.append(["name", "ssn"])
    book.active.append(["Okafor", "412-56-7890"])
    out = io.BytesIO()
    book.save(out)
    (chunk,) = asyncio.run(read_file(None, out.getvalue(), "staff.xlsx", chunk_chars=500)).chunks
    assert chunk.sheet_name == "Staff" and chunk.content == "name, ssn\nOkafor, XXX-XX-7890"


def test_pdfs_are_indexed_page_by_page():
    parser = fake_parser("terms of page 1", "terms of page 2 for SSN 412-56-7890")
    result = asyncio.run(read_file(parser, blank_pdf(2), "contract.pdf", chunk_chars=1500))
    assert [(c.section_title, c.page_number, c.content) for c in result.chunks] == [
        ("Page 1", 1, "terms of page 1"), ("Page 2", 2, "terms of page 2 for SSN XXX-XX-7890")]
    assert (result.title, result.media_type, parser.calls) == ("contract", "application/pdf", ["contract.pdf"])
    assert [(p.n, p.width, p.height) for p in result.pages] == [(1, 612, 792), (2, 612, 792)]


def test_ssns_are_masked_but_eins_kept():
    assert mask_ssns("SSN 412-56-7890 / 412 56 7890, EIN 84-1736295, acct 123456789") == \
        "SSN XXX-XX-7890 / XXX-XX-7890, EIN 84-1736295, acct 123456789"
    # bare 9 digits only after a TIN word; elsewhere they are amounts (spreadsheet cells), accounts, order numbers
    assert mask_ssns("Recipient's TIN: 412567890 | SSN #412567890 | social security number\n412567890") == \
        "Recipient's TIN: XXX-XX-7890 | SSN #XXX-XX-7890 | social security number\nXXX-XX-7890"
    assert mask_ssns("wages, 412567890 | TIN 412567890.00 | SSN 4125678901 | TINY 412567890") == \
        "wages, 412567890 | TIN 412567890.00 | SSN 4125678901 | TINY 412567890"


def test_unsupported_files_are_refused():
    with pytest.raises(UnsupportedDocument):
        file_type("notes.docx", b"PK\x03\x04...")
    with pytest.raises(UnsupportedDocument, match="UTF-8"):
        asyncio.run(read_file(None, b"\xff\xfe\x00bad", "notes.txt", chunk_chars=500))


# --- library --------------------------------------------------------------------------------


def test_search_ranks_by_meaning_within_the_scope(library):
    lease = add(library, draft("warehouse lease renewal rent 4200 monthly", title="lease"))
    add(library, draft("delivery van lease payment schedule", title="van"))
    add(library, draft("sourdough price list per loaf", title="prices"))
    hits = search(library, "warehouse lease rent")
    assert hits[0].title == "lease" and hits[0].similarity is not None and hits[0].similarity > 0.3
    assert [h.title for h in search(library, "lease", document_ids=[lease.id])] == ["lease"]
    assert search(library, "lease", document_ids=["nope"]) == []


def test_keyword_index_finds_exact_identifiers(library):
    add(library, draft("account number 5521-0098 consolidated statement", title="statement"))
    for i in range(30):
        add(library, draft(f"account summary general notes {i}", title=f"note-{i}"))
    hits = search(library, "5521-0098")
    assert hits[0].title == "statement"


def test_documents_are_private_to_their_key_and_deduplicated(library):
    first = add(library, draft("dividends 812.40", title="div"), owner="1")
    again, created = asyncio.run(library.add(draft("dividends 812.40", title="div"), "1", b"text"))
    assert again.id == first.id and not created
    assert search(library, "dividends", owner="2") == []
    assert library.get(first.id, "2") is None and not library.delete(first.id, "2")
    assert [h.title for h in search(library, "dividends", owner=None)] == ["div"]  # admin
    assert library.list(DocumentFilters(), "1")[0] == 1


def test_delete_removes_chunks_from_both_indexes(library):
    doc = add(library, draft("unemployment compensation 8736.00", title="letter"))
    assert library.delete(doc.id, "1")
    assert search(library, "unemployment compensation") == []


def test_changing_the_embedding_model_is_refused(library, tmp_path):
    add(library, draft("interest income 96.12"))
    other = config(tmp_path).embeddings.model_copy(update={"model": "another-embedder"})
    with pytest.raises(IndexMismatch, match="nomic-embed-text"):
        search(Library(library.config, Embedder(other, Embeddings())), "interest")


def test_semantic_scoring_in_batches_matches_brute_force(library, monkeypatch):
    from library.search import semantic

    monkeypatch.setattr("library.search.BATCH", 7)
    texts = [f"form {i} " + " ".join(f"word{(i * j) % 23}" for j in range(5)) for i in range(60)]
    for i, t in enumerate(texts):
        add(library, draft(t, title=f"d{i}"))
    query = "word3 word7 word11"
    q = np.array(fake_vector(query)) / np.linalg.norm(fake_vector(query))
    expected = sorted(texts, key=lambda t: -(np.array(fake_vector(t)) / np.linalg.norm(fake_vector(t))) @ q)[:3]
    with library.store.connect() as conn:
        top = semantic(conn.execute("SELECT seq, embedding FROM document_chunks"), q.astype(np.float32), 3)
        contents = [conn.execute("SELECT content FROM document_chunks WHERE seq = ?", (s,)).fetchone()[0] for s in top]
    assert contents == expected


def test_embeddings_use_task_prefixes(library):
    add(library, draft("interest income"))
    search(library, "interest")
    inputs = library.embedder.transport.inputs
    assert inputs[0].startswith("search_document: ") and inputs[-1] == "search_query: interest"


# --- assistant ------------------------------------------------------------------------------


def assistant_with(tmp_path, replies, provider="ollama", **chat):
    chat_transport = Chat(replies)
    library, assistant = agent.build(config(tmp_path, provider, **chat), chat_transport, Embeddings())
    return library, assistant, chat_transport


def test_assistant_searches_then_answers_with_numbered_sources(tmp_path):
    library, assistant, chat = assistant_with(tmp_path, [
        openai_tool_call({"query": "warehouse rent"}),
        openai_answer("The warehouse rent is $4,200 a month [1]."),
    ])
    add(library, draft("warehouse lease rent 4200 monthly", title="lease"))
    response = asyncio.run(assistant.reply(ask("Warehouse rent?"), "1"))
    assert response.message.content.endswith("[1].")
    assert [(s.n, s.title) for s in response.sources] == [(1, "lease")]
    assert [c.model_dump() for c in response.tool_calls] == [
        {"name": "search_documents", "arguments": {"query": "warehouse rent"}}]
    assert response.usage == {"prompt_tokens": 400, "completion_tokens": 30}
    first, second = chat.requests
    assert chat.paths == ["/v1/chat/completions"] * 2
    assert first["messages"][0]["role"] == "system" and first["tools"][0]["function"]["name"] == "search_documents"
    tool_message = second["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "c1"
    assert tool_message["content"].startswith("[1] lease [document ")


def test_the_scope_limits_every_tool_to_its_documents(tmp_path):
    library, assistant, chat = assistant_with(tmp_path, [
        openai_tool_call({"query": "wages"}),
        openai_tool_call({}, call_id="c2", name="list_documents"),
        openai_answer("Only the Okafor contract is available [1]."),
    ])
    mine = add(library, draft("wages 68412.55 Okafor", title="okafor"))
    other = add(library, draft("wages 51000.00 Patel", title="patel"))
    request = ask("Wages?").model_copy(update={"scope": SearchFilters(document_ids=[mine.id])})
    response = asyncio.run(assistant.reply(request, "1"))
    assert [s.title for s in response.sources] == ["okafor"]
    listed = chat.requests[2]["messages"][-1]["content"]
    assert listed.startswith("1 document(s) match") and other.id not in listed


def test_last_round_has_no_tools_so_the_model_must_answer(tmp_path):
    rounds = 2
    _, assistant, chat = assistant_with(tmp_path, [openai_tool_call({"query": "x"}, f"c{i}") for i in range(rounds)]
                                        + [openai_answer("Nothing found.")])
    assistant.settings = assistant.settings.model_copy(update={"max_tool_rounds": rounds})
    response = asyncio.run(assistant.reply(ask("?"), "1"))
    assert ["tools" in r for r in chat.requests] == [True, True, False]
    assert len(response.tool_calls) == 2 and response.message.content == "Nothing found."


def test_anthropic_wire_format(tmp_path):
    library, assistant, chat = assistant_with(tmp_path, [
        {"content": [{"type": "text", "text": "Let me search."},
                     {"type": "tool_use", "id": "tu1", "name": "search_documents", "input": {"query": "interest"}}],
         "usage": {"input_tokens": 50, "output_tokens": 5}},
        {"content": [{"type": "text", "text": "Interest was $96.12 [1]."}], "usage": {"input_tokens": 80, "output_tokens": 9}},
    ], provider="anthropic")
    add(library, draft("interest income 96.12", title="int"))
    response = asyncio.run(assistant.reply(ask("Interest?"), "1"))
    assert response.message.content == "Interest was $96.12 [1]." and response.usage == {"input_tokens": 130, "output_tokens": 14}
    assert chat.paths == ["/v1/messages", "/v1/messages"]
    first, second = chat.requests
    assert first["system"].startswith("You are the document assistant") and first["tools"][0]["input_schema"]["required"] == ["query"]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][1]["content"][1] == {"type": "tool_use", "id": "tu1", "name": "search_documents",
                                                   "input": {"query": "interest"}}
    assert second["messages"][2]["content"][0]["type"] == "tool_result"


def test_anthropic_merges_one_rounds_tool_results_into_one_user_turn(tmp_path):
    c = config(tmp_path, "anthropic").chat
    calls = [{"id": f"t{i}", "type": "function", "function": {"name": "search_documents", "arguments": "{}"}} for i in (1, 2)]
    body = _anthropic_request(c, [{"role": "user", "content": "q"}, {"role": "assistant", "content": None, "tool_calls": calls},
                                  {"role": "tool", "tool_call_id": "t1", "content": "a"},
                                  {"role": "tool", "tool_call_id": "t2", "content": "b"}], [])
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert len(body["messages"][2]["content"]) == 2


def test_openai_options_and_newer_model_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test")
    _, assistant, chat = assistant_with(tmp_path, [openai_answer("hi")], provider="openai", api_key_env="TEST_OPENAI_KEY",
                                        temperature=None, options={"max_completion_tokens": 500, "reasoning_effort": "low"})
    asyncio.run(assistant.reply(ask("hi"), "1"))
    body = chat.requests[0]
    assert chat.headers[0]["authorization"] == "Bearer sk-test"
    assert "temperature" not in body and "max_tokens" not in body
    assert body["max_completion_tokens"] == 500 and body["reasoning_effort"] == "low"


def test_provider_errors_become_chat_unavailable(tmp_path):
    from agent.agent import ChatUnavailable

    client = ChatClient(config(tmp_path).chat, httpx.MockTransport(lambda r: httpx.Response(500, text="model not found")))
    with pytest.raises(ChatUnavailable, match="HTTP 500: model not found"):
        asyncio.run(client.complete([{"role": "user", "content": "hi"}], []))


# --- HTTP API -------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    chat = Chat([openai_tool_call({"query": "fees"}), openai_answer("A flat fee per order [1].")])
    built = agent.build(config(tmp_path), chat, Embeddings())
    app, admin = make_test_app(parser=fake_parser(), assistant=built)
    with TestClient(app) as client:
        r = client.post("/api-keys", json={"name": "firm"}, headers={"X-API-Key": admin})
        yield SimpleNamespace(client=client, admin={"X-API-Key": admin}, key={"X-API-Key": r.json()["data"]["key"]})


def test_library_and_assistant_routes(api):
    letter = b"# Engagement letter\nWe charge a flat fee per order. Owner SSN 412-56-7890."
    files = {"file": ("engagement.md", letter, "text/markdown")}
    r = api.client.post("/v1/library/documents", files=files, headers=api.key)
    assert r.status_code == 201, r.text
    doc = r.json()["data"]
    assert (doc["type"], doc["title"], doc["chunks"]) == ("md", "engagement", 1)
    assert (doc["media_type"], doc["page_count"], doc["pages"]) == ("text/markdown", 0, [])
    assert api.client.post("/v1/library/documents", files=files, headers=api.key).status_code == 200  # same file

    r = api.client.post("/v1/library/search", json={"query": "fee"}, headers=api.key)
    (hit,) = r.json()["data"]["hits"]
    assert hit["section_title"] == "Engagement letter" and "XXX-XX-7890" in hit["content"] and "412-56" not in hit["content"]

    r = api.client.post("/v1/assistant/chat", json={"messages": [{"role": "user", "content": "What are the fees?"}]},
                        headers=api.key)
    assert r.status_code == 200, r.text
    answer = r.json()["data"]
    assert answer["message"] == {"role": "assistant", "content": "A flat fee per order [1]."}
    assert answer["sources"][0]["n"] == 1 and answer["sources"][0]["document_id"] == doc["id"]

    assert api.client.get("/v1/library/documents", params={"q": "engage"}, headers=api.key).json()["data"]["count"] == 1
    assert api.client.get("/v1/library/documents", params={"q": "nope"}, headers=api.key).json()["data"]["count"] == 0
    assert api.client.get(f"/v1/library/documents/{doc['id']}", headers=api.admin).status_code == 200  # admin sees all
    assert api.client.delete(f"/v1/library/documents/{doc['id']}", headers=api.key).status_code == 204
    assert api.client.get(f"/v1/library/documents/{doc['id']}", headers=api.key).status_code == 404


def test_library_routes_validate_input(api):
    assert api.client.post("/v1/library/search", json={"query": ""}, headers=api.key).status_code == 422
    r = api.client.post("/v1/library/documents", files={"file": ("a.docx", b"PK\x03\x04", "application/zip")}, headers=api.key)
    assert r.status_code == 415
    assert api.client.post("/v1/assistant/chat", json={"messages": []}, headers=api.key).status_code == 422
    assert api.client.post("/v1/library/search", json={"query": "x"}).status_code == 401


# --- tools ----------------------------------------------------------------------------------------


def run_tool(name: str, args: dict, library, owner="1", scope=None) -> str:
    from agent.tools import TOOLS, ToolContext

    ctx = ToolContext(library=library, scope=scope or SearchFilters(), owner=owner)
    return asyncio.run(TOOLS[name].run(args, ctx))


def test_list_documents_tool_stays_within_owner_and_scope(library):
    lease = add(library, draft("warehouse lease", title="lease"))
    add(library, draft("price list", title="prices"))
    out = run_tool("list_documents", {}, library)
    assert out.startswith("2 document(s) match:") and f"- {lease.id} | lease | txt file | 1 passage(s) | added " in out
    assert run_tool("list_documents", {"q": "leas"}, library).count("\n") == 1
    assert run_tool("list_documents", {}, library, owner="2").startswith("0 document(s)")
    scoped = run_tool("list_documents", {}, library, scope=SearchFilters(document_ids=[lease.id]))
    assert scoped.startswith("1 document(s) match") and "prices" not in scoped
    paged = run_tool("list_documents", {"limit": 1, "offset": 1}, library)
    assert paged.startswith("2 document(s) match; showing 2-2:")


def test_assistant_dispatches_registered_tools_and_lists_the_calls(tmp_path):
    library, assistant, chat = assistant_with(tmp_path, [
        openai_tool_call({}, name="list_documents"),
        openai_tool_call({"document_id": "x"}, call_id="c2", name="nope"),
        openai_answer("One lease is on file."),
    ])
    add(library, draft("warehouse lease", title="lease"))
    response = asyncio.run(assistant.reply(ask("What is on file?"), "1"))
    assert [c.name for c in response.tool_calls] == ["list_documents", "nope"] and response.sources == []
    assert {t["function"]["name"] for t in chat.requests[0]["tools"]} == {
        "search_documents", "browse_knowledge", "read_document", "list_documents"}
    assert chat.requests[1]["messages"][-1]["content"].startswith("1 document(s) match")
    assert chat.requests[2]["messages"][-1]["content"] == "error: unknown tool 'nope'"
