# Business Partner

FastAPI service and dashboard for an AI business partner. The owner uploads business documents and describes the business; the partner reads the documents, then interviews the owner from a first-principles question bank (identity, offering, customers, revenue, operations, departments, roles, finance, sales, tools, data, information flow, compliance, goals), keeps a business profile, organizes uploaded documents into it, recommends MCP connectors for the software the business uses, and drafts role assistants (accountant, marketer, ...) as plain JSON specs. Assistants share engineered context (deterministic layers with budgets), act through connectors, and run read-only tool calls freely while writes follow a per-assistant policy (`auto`, `ask` → approvals queue, `deny`). Everything the workspace knows (uploaded files, the business profile, the owner's discovery answers, notes) is kept in one vector index that can be searched and browsed source by source, so rarely used material stays discoverable. Models run locally on Ollama by default; cloud providers are opt-in.

Documents capability: classification and extraction of 15 US tax form types from digital PDFs and scanned documents into typed JSON with structured review flags, a document library with a review dashboard (each value checked side by side against where it was read on the page) and a document assistant with read-only tools over the stored documents.

![Dashboard demo: assistant, document upload, classification and review](docs/assets/demo.gif)

Output requires human review against the source document. See [DISCLAIMER.md](DISCLAIMER.md) and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

> **v2 breaking change.** `validation.warnings` (strings) is replaced by `validation.flags` (`{field, code, message}` objects), and the assistant response's `searches` count by `tool_calls`. A library database created before v2 is refused with `500 outdated_library`: delete `data/library.db` and add the documents again.

## Features

- Business partner chat: interview, profile updates (JSON merge patch), document organizing, connector recommendations, assistant drafts; it receives the screen the owner is on.
- Role assistants as JSON specs: connectors, knowledge scope, shared notes topics, write policy with per-tool overrides; context preview; approvals queue.
- Knowledge index: files and workspace records (profile, discovery answers, notes) in one hybrid search; a map of every source and passage with what was never retrieved; search results spread over sources and name the ones not shown.
- Connector store: cloud storage (Google Drive and Docs, Dropbox, Box, OneDrive/SharePoint through Microsoft 365) and business tools as MCP connectors, from the store or by hand, tokens encrypted at rest ([docs/CONNECTORS.md](docs/CONNECTORS.md)).
- Workspace database: a built-in connector giving the owner their own SQLite databases (tables, rows, CSV import/export, SQL) that assistants read and, under their write policy, change.
- Contextual hints for the dashboard from its state and recent interactions.
- Single-form, bulk (multi-file, multi-form) and classify-only routes; PDF, PNG, JPEG, TIFF, BMP, WEBP detected from file bytes.
- Docling layout/OCR, classification by the `tev1` model or by printed headings, field mapping by an Ollama LLM.
- Amounts and TINs verified against their printed labels and positions; every kept value carries its source box.
- Document library: original files, extracted forms, per-field review decisions, hybrid (embedding + keyword) search.
- Review dashboard (`web/`): page viewer with source boxes, confirm / correct / reject, approval, assistant with citations.
- Assistant over the library via OpenAI-compatible or Anthropic chat APIs; local `qwen3.5:4b` + `nomic-embed-text` by default.
- API-key auth (client / admin), per-key rate limits, job gate, request IDs, uniform error envelope.
- Optional n8n intake and review workflow.

## Setup

### Prerequisites

| Requirement | Version / notes |
|---|---|
| Python | 3.12+ (`requires-python = ">=3.12"`) |
| [uv](https://docs.astral.sh/uv/) | Dependency and run tool (`uv.lock`) |
| Node.js | 20.19+ or 22.12+ (required by Vite 7); dashboard only |
| [Ollama](https://ollama.com) | Running server, reachable at `OLLAMA_URL` |

Ollama models:

```sh
ollama pull qwen3.5:4b         # field extraction and assistant chat (required)
ollama pull nomic-embed-text   # library search embeddings
ollama pull tev1               # classifier (optional; uses Ollama's systemone API)
```

Without `tev1`, set `TEV_MODEL=none` in `.env`: forms are identified by printed headings only (missing or unreadable headings produce `unknown`). The extraction LLM is still required.

### Backend

From the repository root:

```sh
uv sync --locked
cp .env.example .env                    # PowerShell: Copy-Item .env.example .env
uv run main.py create-key --name admin --admin
uv run main.py create-key --name client
uv run main.py serve --host 127.0.0.1 --port 8000
```

Each key is printed once; store it. Client keys call document, library and assistant routes; admin keys also manage keys and see every key's documents. `create-key --days N` sets an expiry. Docling loads its models at startup and may download weights on first run.

### Frontend

```sh
cd web
npm install
npm run dev      # http://localhost:5173; API paths proxied to http://127.0.0.1:8000 (override with API_URL)
npm run build    # web/dist, served by the API at /
```

The API mounts `web/dist` only if `web/dist/index.html` exists at startup: restart the API after the first build. Without a build, `/` redirects to `/docs`.

## Usage

- Dashboard: open `http://localhost:8000/` (built) or `http://localhost:5173/` (dev) and sign in with the client key.
- API docs: `http://localhost:8000/docs` (Swagger), `/redoc`, `/openapi.json`. In Swagger, clear unused optional fields containing the placeholder `string`.
- Health: `GET /health` returns 200 even when `data.status` is `degraded`; read the body.

In Windows PowerShell, call `curl.exe` (plain `curl` may be an alias of `Invoke-WebRequest`). Multipart examples are identical in both shells; JSON-body examples below use bash quoting (in PowerShell, put the body in a file and pass `-d "@body.json"`).

```sh
curl -H "X-API-Key: YOUR_CLIENT_KEY" -F "file=@tests/samples/w2.pdf" http://localhost:8000/v1/documents/extract
curl -H "X-API-Key: YOUR_CLIENT_KEY" -F "file=@tests/samples/w2.pdf" -F "client=Gonzalez" -F "tax_year=2025" http://localhost:8000/v1/library/documents
```

## API reference

### Conventions

- Auth: `X-API-Key` header on every route except `GET /health` (and the first `POST /api-keys` when `ALLOW_KEY_BOOTSTRAP=true` and no keys exist).
- Success: `{"data": ...}`. Error: `{"error": {"code", "message", "request_id", "details"}}`.
- `X-Request-ID` is returned on every response; a caller-supplied value is reused.
- Library, review and assistant routes are owner-scoped: a key sees only documents it added (admin: all). Another key's document is `404`.
- Business, partner, assistant, approval, notes and connector routes work in the calling key's own workspace (`business_owner`: the key id), admin keys included: a workspace is never shared. Another workspace's entity is `404`.

### Routes

| Route | Auth | Purpose |
|---|---|---|
| `POST /v1/documents/extract` | Client | Extract one form from one file (`file`; `?document_type=` skips splitting and classification) |
| `POST /v1/documents/extract/bulk` | Client | Extract every form from one or more files (`files`, repeated) |
| `POST /v1/documents/classify` | Client | Classify exactly one of `file` or `text` |
| `GET /v1/document-types` | Client | Supported forms: `id`, `name` (`W-2`), `title`, field schema |
| `POST /v1/library/documents` | Client | Store a document: original file, forms, search chunks |
| `GET /v1/library/documents` | Client | List documents (filters, review counts) |
| `GET` / `DELETE /v1/library/documents/{id}` | Client | Read (pages, forms) / delete one document |
| `GET /v1/library/documents/{id}/pages/{n}` | Client | One page as PNG (`?width=`) |
| `GET /v1/library/documents/{id}/file` | Client | Original bytes (`Content-Disposition: attachment`) |
| `GET /v1/library/stats` | Client | Dashboard counts (list filters) |
| `POST /v1/library/search` | Client | Hybrid search |
| `GET /v1/library/forms/{form_id}` | Client | A form as review checks |
| `PUT` / `DELETE /v1/library/forms/{form_id}/reviews/{field}` | Client | Set / clear the decision on one field |
| `POST /v1/library/forms/{form_id}/approve` | Client | Approve a form |
| `POST /v1/library/forms/{form_id}/reopen` | Client | Set a form back to `pending` |
| `POST /v1/assistant/chat` | Client | Ask the document assistant about library documents |
| `GET /v1/workspace` | Client | Workspace summary: profile and interview progress, counts, recommended connectors |
| `POST /v1/workspace/hints` | Client | Contextual hints for the screen (`state`) and recent `events` |
| `GET` / `PUT /v1/business/profile` | Client | Read / replace the business profile |
| `GET /v1/business/interview` | Client | Interview progress per area and the next questions |
| `POST /v1/business/interview/answers` | Client | Record (or replace) one answer |
| `POST /v1/partner/chat` | Client | Talk to the business partner |
| `GET /v1/business/documents` | Client | Library documents organized into the profile |
| `PUT /v1/business/documents/{document_id}` | Client | Organize (or move) a library document |
| `GET` / `POST /v1/business/notes` | Client | The shared notes board (`?topic=`) / post a note as the owner |
| `GET /v1/assistants/schema` | Client | JSON Schema of an assistant spec |
| `GET` / `POST /v1/assistants` | Client | List / create assistants (created as `draft`) |
| `GET` / `PUT` / `DELETE /v1/assistants/{id}` | Client | Read / replace the spec (status kept) / delete |
| `PUT /v1/assistants/{id}/status` | Client | `draft`, `active` or `paused` |
| `GET /v1/assistants/{id}/context` | Client | Context layers and tools exactly as a run sends them |
| `POST /v1/assistants/{id}/run` | Client | Give an active assistant a task |
| `GET /v1/approvals` | Client | The approvals queue (`?status=`), newest first |
| `POST /v1/approvals/{id}/decision` | Client | Approve (runs the call; `always` sets the tool to `auto`) or reject |
| `/v1/connectors...` | Client | Connector store, installs, checks, tools, OAuth: [docs/CONNECTORS.md](docs/CONNECTORS.md) |
| `GET /v1/knowledge` | Client | The whole index by source: totals, sections, passages never retrieved |
| `GET /v1/knowledge/{document_id}/passages` | Client | A source's passages as indexed, with retrieval counts |
| `POST /v1/knowledge/search` | Client | Search files and workspace records together |
| `/v1/databases/{connector_id}...` | Client | Tables, rows, SQL, CSV import and export of a workspace database |
| `GET /health` | None | Parser and model readiness: `status` (`ok` / `degraded`), `docling_loaded`, `ollama_reachable`, `models` |
| `GET /auth/me` | Client | The current key |
| `POST` / `GET /api-keys` | Admin | Create (`name`, `is_admin`, `expires_in_days`) / list keys |
| `DELETE /api-keys/{id}` | Admin | Revoke a key |

"Client" means any valid key (client or admin).

### Extraction

`POST /v1/documents/extract` returns in `data`: `document_type`, `form_name`, `classification`, `fields`, `validation`, `document`, `extraction_model`, `timings_ms`.

- `fields` follows the schema from `GET /v1/document-types`: amounts are numbers, dates normalized, checkboxes booleans or `null`; missing scalars are generally `null`, repeated fields are arrays.
- `validation`: `flags`, field counts, `sources`; `valid` is true when there are no flags. A valid schema does not prove accuracy or completeness.
- `document.conversion` is `partial` when Docling reported errors (`conversion_errors`); `document.missing_pages` lists pages with no text.
- A multi-form file returns `422 multiple_forms` (use bulk); an unidentified form `422 unsupported_document_type`; a file with no readable text `422 unreadable_document`.

`POST /v1/documents/extract/bulk` returns `data.files`, `data.summary`, `data.timings_ms`. Each file has metadata, `document`, and `forms[]` with source pages and a status:

| Form status | Meaning |
|---|---|
| `ok` | Identified and extracted; inspect `validation.flags` |
| `unsupported` | Not identified as a supported form; `fields` is `null` |
| `duplicate` | Same type and every extracted value identical to an earlier form in the file (`duplicate_of`); forms with no TIN and no amount are never duplicates |

A file that fails to parse is `status: failed` with `error`; other files continue. Upload validation and model backend errors fail the whole request. `summary.forms` and `summary.by_type` count `ok` forms only. Processing is synchronous and sequential: large statements can take minutes, so set client timeouts or send one file per request.

`POST /v1/documents/classify` returns one classification from the configured classifier. Digital PDFs use embedded text from the first two pages when available; scans go through OCR. `document` can be `null` (text input or the embedded-text path).

### Flags

Each flag is `{field, code, message}`. `field` is a path in `sources` syntax (`employee.tin`, `box12[0].amount`) or `null` for the whole form; `message` never contains a full TIN. Codes are defined in [core/flags.py](core/flags.py) (`Flag.code` in the OpenAPI schema).

| `code` | Meaning |
|---|---|
| `not_printed` | Value removed: not printed in the document |
| `wrong_label` | Value removed: printed only under another field's label |
| `unlabeled` | Value kept, but not found in its labeled box |
| `unparseable` | Value dropped: not a valid amount, date, TIN, ... |
| `multiple_values` | Several printed values in one box; the first was kept |
| `text_as_json` | The model returned JSON for a text field; flattened |
| `no_output` | No usable JSON from the extraction model (form-level) |
| `inconsistent` | Amounts don't add up (e.g. W-2 box 4 vs 6.2% of box 3); on the field that looks off |
| `partial_conversion` | File only partly converted (form-level) |
| `missing_page` | A page in the form's range produced no text (form-level) |
| `uncertain_type` | Identified by printed heading; classifier not confident (form-level) |

### Grounding and sources

With `STRICT_GROUNDING=true` ([core/grounding.py](core/grounding.py), run by `LLMExtractor.extract`):

- Amounts and TINs must sit in the box of their own label. Not printed at all (zero included: a blank box is not `0.00`) → removed, `not_printed`. Printed only under another label → removed, `wrong_label`. Printed but not in a labeled box, or label not found → kept, `unlabeled`.
- Other values (names, addresses, codes, dates, years, checkboxes) are only located, never removed or flagged.
- `validation.sources` maps each kept amount/TIN, located value and table row (`transactions[3]`) to `{label, page, box}`; `box` is left, top, right, bottom on a page 1000 units wide, origin top-left. Values not found have no entry.

### Library

`POST /v1/library/documents` (multipart): `file`, optional `client`, `tax_year`, `title`, `location`, `extract` (default `true`). Returns `201`, or `200` with the stored document when the same file was already added by this key.

- Accepted: PDF and images (form extraction, as bulk; up to `BULK_MAX_PAGES` pages), `.txt`, `.md`, `.csv`, `.xlsx` (no forms). `extract=false` (what the dashboard sends for business documents): PDFs and images are parsed by Docling (OCR where there is no text layer, up to `BULK_MAX_PAGES` pages) and stored as one text chunk set per page (`document_type: text`, section `Page n`), with no forms, no classification, no extraction LLM and no review (`review_status: null`); text files are chunked as always (the flag does not apply). The upload still holds a job slot.
- Forms are stored with status, pages, classification, fields and validation; `ok` forms start `review_status: pending`.
- Search chunks: each `ok` form as `path: value` lines with form ID and tax year, plus text of pages without a form. Text files split by Markdown heading, CSV/sheet rows (header repeated) or paragraphs, at most `library.chunk_chars` each.
- SSNs are masked to the last four digits (`XXX-XX-1234`) in every chunk before storage or embedding: 3-2-4 digits with one separator (dash or space) always, 9 bare digits only after SSN, ITIN, TIN or social security (elsewhere they may be amounts, account or control numbers). EINs (`12-3456789`) are kept. Stored form fields keep values as extracted.
- Originals are stored under `library.files` (default `data/files/`) named by SHA-256, shared across keys, removed with the last document using them.

| Route | Contract |
|---|---|
| `GET /v1/library/documents` | Query: `client`, `tax_year`, `document_type` (form ID or `text`), `review_status` (`pending`: a form awaits approval; `approved`: every `ok` form approved), `q` (title or client substring), `origin` (`upload`, the default: uploaded files; `workspace`: the workspace's own index records), `limit` (1–200, default 50), `offset`, `order` (`newest` / `oldest`). `data: {count, documents[]}`; each: `id, title, type, media_type, length_bytes, location, content_hash, client, tax_year, created_at, chunks, document_types, page_count, review_status` (`null` without forms), `forms_pending, forms_approved, open_flags` |
| `GET /v1/library/documents/{id}` | Document plus `pages: [{n, width, height}]` (PDF points or image pixels) and `forms: [{id, index, status, pages, document_type, form_name, duplicate_of, review_status, open_flags}]` |
| `GET /v1/library/documents/{id}/pages/{n}` | `image/png`; `width` 100–2400 (default 1200). `ETag: "<sha256>-<n>-<width>"` (`If-None-Match` → 304), `Cache-Control: private, max-age=86400`. Map a source `box` onto the image by multiplying by `width / 1000` |
| `GET /v1/library/stats` | List filters. `data: {documents, forms` (`ok`), `forms_by_type, forms_by_review_status: {pending, approved}, open_flags, clients: [{client, documents, forms_pending, open_flags}]}` |
| `POST /v1/library/search` | Body `{query, filters: {client, tax_year, document_type, document_ids}, limit}`; `limit` default `library.default_results`, max `library.max_results` |

`open_flags` counts flagged fields without a review decision.

Search: filters are applied in SQLite first; remaining chunks are ranked by exact cosine similarity (batched) and by SQLite FTS5 keywords, then merged by reciprocal rank fusion ([library/search.py](library/search.py)). One document fills at most half of the results while other documents match. Each hit's `similarity` is the cosine value, `null` for keyword-only matches.

### Knowledge index

One index holds the uploaded files and the workspace's own records, so nothing the business has told the partner depends on fitting into a prompt.

- Workspace records ([business/memory.py](business/memory.py)): `Business profile` (a section per profile topic, department and role), `Discovery answers` (per interview area, each question with the owner's answer) and `Shared notes` (per topic). They are library documents whose `location` starts with `workspace://`; they are rewritten when their text changed, before any search (knowledge routes, partner chat, assistant runs, document assistant). `POST /v1/library/documents` refuses a `location` with that prefix (`400`).
- `GET /v1/knowledge` (query `q`, `origin`, `unused`, `limit` 1–200, `offset`) → `{sources, passages, never_retrieved, count, items[]}`; the totals cover the whole index (within `origin`), `q` and `unused` narrow `items`. Each item: `document_id, title, type, location, created_at, passages, never_retrieved, last_retrieved_at, sections[]` (the first 12 section titles), `origin` (`upload` / `workspace`), and `department`, `kind` when the document is organized. `unused=true` lists only sources with passages never retrieved, most first.
- A passage counts as retrieved when a search returns it (any route or assistant) or an assistant reads it with `read_document`; browsing on the dashboard does not count.
- `GET /v1/knowledge/{document_id}/passages` (`limit` 1–100, `offset`) → `{document_id, title, count, passages: [{chunk_id, index, section_title, page_number, sheet_name, document_type, content, retrievals, last_retrieved_at}]}`.
- `POST /v1/knowledge/search` body `{query, filters, limit}` → `{hits, other_sources: [{document_id, title}]}`: `other_sources` (at most 5) are documents that matched by keyword, or nearly as closely as the best hit, without a passage among `hits`.

### Workspace databases

Adding the store listing `workspace-database` (`POST /v1/connectors` with `{listing_id, name}`) creates a SQLite file `<business.database folder>/databases/<connector id>.db`; removing the connector deletes it. A workspace can hold several. Routes under `/v1/databases/{connector_id}` ([api/routes/databases.py](api/routes/databases.py)); another key's database is `404`, a refused statement `422 invalid_database_request`.

| Route | Contract |
|---|---|
| `GET /tables` | `[{name, columns: [{name, type, required, primary_key}], rows}]`; `type`: `text, integer, real, date, boolean` |
| `POST /tables` | Body `{name, columns: [{name, type, required}]}`; an integer `id` key is added. Names: letters, digits, `_` |
| `POST /tables/import` | Multipart `name`, `file` (UTF-8 CSV, header row; at most 50 000 rows): a new table in one transaction. A column is `integer` or `real` only when every value is a plain number; anything else (`02134`, `1_000`) stays text |
| `DELETE /tables/{table}` | Drops the table |
| `GET /tables/{table}/rows` | `limit` (1–500, default 50), `offset` → `{columns, rowids, rows, total}`; `rowids` is empty for a table created `WITHOUT ROWID` (readable; changed through SQL only) |
| `POST /tables/{table}/rows`, `PUT` / `DELETE .../rows/{rowid}` | Body `{values: {column: value}}`; insert returns the rowid |
| `GET /tables/{table}/export` | The table as `text/csv` |
| `POST /query` | Body `{sql, write}` → `{columns, rows, truncated, changed}`: one statement, at most 500 rows; without `write` only `SELECT` runs |

Assistants given the connector get its tools ([business/database.py](business/database.py)): `list_tables`, `describe_table`, `query` (read-only, always run) and `create_table`, `insert_rows`, `update_rows`, `delete_rows`, `execute` (writes, under the assistant's policy). `where` columns of `update_rows` / `delete_rows` must exist in the table and may not be empty. Limits: 5 s per statement, 512 MB per file; statements cannot attach other files or change PRAGMAs.

### Review

```sh
curl -H "X-API-Key: YOUR_CLIENT_KEY" http://localhost:8000/v1/library/forms/FORM_ID
curl -X PUT -H "X-API-Key: YOUR_CLIENT_KEY" -H "Content-Type: application/json" -d '{"decision": "corrected", "value": "68,412.55"}' http://localhost:8000/v1/library/forms/FORM_ID/reviews/wages_tips_other_comp
curl -X POST -H "X-API-Key: YOUR_CLIENT_KEY" http://localhost:8000/v1/library/forms/FORM_ID/approve
```

`GET /v1/library/forms/{form_id}`: form summary plus `document_id, classification, text_layer, extraction_model, approved_by, approved_at`, and

- `checks[]`: every scalar schema field in schema order (empty ones included); list fields contribute extracted rows only. Each: `field`, `label`, `group`, `kind` (`money, percent, tin, date, check, state, year, month, acquired, choice, text`), `options` (`choice`), `value`, `source` (`{label, page, box}` or `null`), `flags`, `review` (`{decision, value, note, reviewer, reviewer_id, updated_at}` or `null`).
- `flags`: form-level flags. `checked`, `total`, `open_flags`. `corrected_fields`: fields with every decision applied (`null` for unsupported forms).

Rules ([library/review.py](library/review.py), [library/service.py](library/service.py)):

- `PUT .../reviews/{field}` body `{decision, value?, note?}`: `confirmed`; `corrected` (`value` required, parsed like extracted values, else `422 invalid_value`); `rejected` (`null` in `corrected_fields`). Returns the check; records the key's id and name. `DELETE` clears it. Unknown field → `404`; unsupported/duplicate form → `409 not_reviewable`.
- `POST .../approve` requires a decision on every flagged field, else `409 review_incomplete` with `details.undecided`. `reopen`, or any `PUT`/`DELETE` on an approved form, sets it back to `pending`.
- A decision that changes values rebuilds the form's search chunks from `corrected_fields` in the same transaction.

### Document assistant

```sh
curl -H "X-API-Key: YOUR_CLIENT_KEY" -H "Content-Type: application/json" -d '{"messages": [{"role": "user", "content": "What were the 2025 wages?"}], "scope": {"client": "Gonzalez"}}' http://localhost:8000/v1/assistant/chat
```

Stateless: send the conversation so far, ending with the user's message. `scope` (`client`, `tax_year`, `document_type`, `document_ids`) bounds every tool; the model can narrow it, not widen it. Up to `assistant.max_tool_rounds` tool rounds, then the model must answer, citing excerpts as `[n]`. Response `data`: `message`, `sources` (every retrieved excerpt, numbered as cited), `tool_calls` (`[{name, arguments}]`), `model`, `usage`.

Tools ([agent/tools.py](agent/tools.py)), all read-only; errors return to the model as `error: ...` text:

| Tool | Arguments | Returns |
|---|---|---|
| `search_documents` | `query`, `client`, `tax_year`, `document_type`, `limit` | Numbered excerpts with document ID, client, form, year, page; then the relevant sources not shown |
| `browse_knowledge` | `q`, `unused_only`, `limit`, `offset` | The index by source: sections, passage count, passages never retrieved |
| `read_document` | `document_id`, `offset`, `limit` | A source in full, passage by passage, numbered like search excerpts |
| `list_documents` | `client`, `tax_year`, `document_type`, `review_status`, `limit` | One line per document with review counts and open flags |
| `get_document` | `document_id` | Metadata, forms with review status and open flags, reviewed values (SSNs masked) |
| `classify_document` | `document_id`, `pages` | Classifier result on the stored file (`pages`: PDF subset) |
| `extract_document` | `document_id`, `document_type` | Fields and flags, not saved; holds an extraction slot (`MAX_CONCURRENT_JOBS`) |

### Business workspace

Profile ([business/schema.py](business/schema.py) `BusinessProfile`): `name, summary, industry, business_model, offerings[], customers, locations[], team_size, stage, goals[], pain_points[], departments[{name, purpose, head, responsibilities[]}], roles[{title, department, people[], duties[], tools[], reports_to}], tools[{name, category, used_for, departments[], listing_id}], flows[{source, target, what, cadence, via}], financials{revenue_streams[], cost_centers[], pricing, currency, fiscal_year_end, accounting_method}, compliance[], updated_at` (set by the server); a tool's `listing_id` is the store listing that connects it. `PUT` replaces it; unknown fields → `422 invalid_request`.

Interview ([business/questions.py](business/questions.py)): 37 questions in 14 areas, each `{id, area, text, purpose, fills}`. A question is done when answered or when every profile field it `fills` has content. `GET /v1/business/interview` → `{answered, total, complete, areas: [{area, label, answered, total}], next}`: `complete` when every required question (at least one per area) is done; `next` holds at most 5 open questions, required first, then those of the least covered areas. `POST .../answers` body `{question_id, answer}`; unknown id → `404`.

Partner chat:

```sh
curl -H "X-API-Key: YOUR_CLIENT_KEY" -H "Content-Type: application/json" -d '{"messages": [{"role": "user", "content": "We are a bakery with six people."}], "ui_state": {"page": "/partner"}}' http://localhost:8000/v1/partner/chat
```

Stateless: send the conversation so far. `ui_state` (`{page, entity: {kind, id, title}, detail}`) is the screen the message was sent from. Up to `business.partner.max_tool_rounds` tool rounds. Response `data`: the document assistant's fields (`message, sources, tool_calls, model, usage`) plus `profile_changed`, `assistants_changed` (refetch) and `interview`. Rate limit: `ASSISTANT_RATE_CALLS`, shared with the document assistant and assistant runs.

Partner tools ([business/partner.py](business/partner.py)); errors return to the model as `error: ...` text:

| Tool | Arguments | Does |
|---|---|---|
| `next_questions` | | Progress per area and the next questions |
| `record_answer` | `question_id`, `answer` | Stores an answer |
| `update_profile` | `patch` | RFC 7386 merge patch on the profile (lists replace whole lists), validated |
| `search_documents`, `list_documents`, `browse_knowledge`, `read_document` | as the document assistant | Over the key's own library; the list marks organized documents |
| `organize_document` | `document_id`, `department`, `kind`, `summary` | Places a library document in the profile |
| `recommend_connectors` | | Store listings matching the profile's tools (by name, capability or category), installed or not |
| `list_connectors` | `tools` | Installed connectors; with `tools: true` their tools (read-only or write) |
| `create_assistant` | `spec` | Creates a `draft` assistant (`created_by: partner`) |
| `update_assistant` | `assistant_id`, `spec` | Replaces a spec; an active or paused assistant returns to `draft` |
| `post_note` | `topic`, `text` | Posts on the notes board as `partner` |

Organized documents: `PUT /v1/business/documents/{document_id}` body `{department?, kind, summary?}` → `{document_id, title, department, kind, summary, organized_at}`; a document the key does not own → `404`. Lists leave out documents since deleted from the library.

Notes: `{id, topic, text, author, created_at}`, newest first; topics compare case-insensitively. `author` is `owner`, `partner` or an assistant's name.

Workspace summary `data`: `business_name, profile_fields, profile_total, interview, documents, organized_documents, assistants: {draft, active, paused}, connectors: {untested, connected, needs_auth, error}, pending_approvals, recommended_connectors` (store listings named by a profile tool, by name or capability, not installed).

Hints: `POST /v1/workspace/hints` body `{state: UiState, events: [{type: navigate|select|action|error|idle, page, target, detail, at}]}` (at most 50, oldest first) → `{hints: [{id, title, body, tone: info|suggestion|warning, action: {label, href} | null}]}`, at most 3, most relevant first. Rules and ids: [business/hints.py](business/hints.py); ids are stable so dismissals can be remembered.

### Assistants and approvals

```json
{"name": "Accountant", "role": "Keeps the books and prepares the monthly report", "department": "Finance",
 "instructions": "...", "connectors": ["<connector id>"], "knowledge": {"departments": ["Finance"], "document_kinds": []},
 "shares": ["finance", "month-end"], "policy": {"default": "ask", "tools": {"<connector id>/list_invoices": "auto"}},
 "max_tool_rounds": 6}
```

- `POST` / `PUT /v1/assistants[/{id}]` take the spec (`GET /v1/assistants/schema`); responses add `id, status, created_by, created_at, updated_at`. `422 invalid_assistant`: a connector the key has not installed, a `policy.tools` key that is not `<connector id>/<tool>` of its connectors, or a name already used in the workspace (case-insensitive).
- `POST .../run` body `{messages}`: `409 assistant_inactive` unless `active`. Response `data`: `message, tool_runs: [{connector_id, tool, arguments, read_only, outcome: ran|pending_approval|denied|failed, approval_id, result}], model, usage` (`result`: the first 2000 characters, followed by `\n[truncated]` when longer).
- Tools offered: `search_documents`, `browse_knowledge` and `read_document` over its knowledge (organized documents matching `knowledge`; empty lists: every organized document; plus the workspace's own index records), `read_notes` / `post_note` (its `shares` topics; offered when it has some), and the tools of its connected connectors as `<connector id>__<tool>` (characters outside `[a-zA-Z0-9_-]` become `_`; longer than 64 or taken: the first 55 characters, `_` and an 8-digit hash, salted until the name is free).
- Policy: read-only connector tools (MCP `readOnlyHint`) always run. Writes use `policy.tools["<connector id>/<tool>"]`, else `policy.default`: `auto` runs, `ask` queues an approval (`reason`: the assistant's text of that turn) and tells the model it awaits approval, `deny` refuses. Built-in tools are outside the policy.
- `GET .../context` → `{layers: [{name: business|role|team|notes, text}], tools, chars}`, exactly the system messages and tools of a run. Layer rules: [docs/DEVELOPING.md](docs/DEVELOPING.md#context-layers).
- Approvals: `{id, assistant_id, assistant_name, connector_id, tool, arguments, reason, status: pending|executing|rejected|executed|failed, result, created_at, decided_at, decided_by, note}`. `POST .../decision` body `{approve, note?, always?}`: the approval is first claimed (`executing`, or `rejected` for a reject) in one statement, then approve runs the call (`executed` or `failed` with the tool's output as `result`); `always` sets that tool to `auto` in the assistant's policy only when the call executed and the assistant still has the connector. Not `pending` (including `executing`: another decision is running it) → `409 already_decided`. Notes reach assistants as delimited data, not instructions; a tool its server marks read-only always runs, whatever the policy ([docs/DEVELOPING.md](docs/DEVELOPING.md#trust-boundaries)). `decided_by` is the key's name.

### Error codes

| HTTP | `error.code` |
|---|---|
| 400 | `bad_request` |
| 401 / 403 | `unauthorized` / `forbidden` (also: stdio connector with a client key) |
| 404 | `not_found` |
| 409 | `index_mismatch` (library built with another embedding model); `review_incomplete` (`details.undecided`); `not_reviewable`; `assistant_inactive` (run of a draft or paused assistant); `already_decided` (approval not pending) |
| 413 | `payload_too_large`, `too_many_pages` |
| 415 | `unsupported_media_type` (`details.supported`) |
| 422 | `unreadable_document`, `unsupported_document_type`, `multiple_forms` (`details.forms`), `invalid_request` (`details.errors`), `invalid_value` (`details.field`), `invalid_assistant` (spec names an uninstalled connector, a stray policy key or a duplicate name), `invalid_connector` (e.g. remote transport without URL), `invalid_database_request` (a bad table or column name, SQL that fails or is not allowed) |
| 429 | `rate_limited` (`Retry-After`) |
| 500 | `internal_error`; `outdated_library` (pre-v2 library database); `outdated_workspace` (workspace tables of another version in `business.database`) |
| 502 | `connector_failed` (a connector could not be reached or failed) |
| 503 | `model_unavailable` (`Retry-After: 10`; unreachable or rejecting provider); `busy` (all job slots and queue taken, `Retry-After: 30`) |

### Supported forms

Form IDs are used by `document_type`; definitions in [core/forms.py](core/forms.py).

| ID | Form | Main data |
|---|---|---|
| `w2` | W-2 | Wages, withholding, coded boxes, state/local rows |
| `1099_nec` | 1099-NEC | Nonemployee compensation |
| `1099_misc` | 1099-MISC | Rents, royalties, other income |
| `1099_int` | 1099-INT | Interest income and related amounts |
| `1099_div` | 1099-DIV | Dividends and capital gain distributions |
| `1099_b` | 1099-B | Sales, proceeds, basis, wash sales, transaction categories |
| `1099_r` | 1099-R | Retirement distributions and distribution codes |
| `1099_g` | 1099-G | Government payments |
| `1099_k` | 1099-K | Payment transactions and monthly amounts |
| `ssa_1099` | SSA-1099 | Social Security benefits |
| `1098` | 1098 | Mortgage interest and loan details |
| `1098_t` | 1098-T | Tuition, scholarships, student status |
| `1098_e` | 1098-E | Student loan interest |
| `1095_a` | 1095-A | Coverage, covered individuals, monthly and annual amounts |
| `k1_1065` | Schedule K-1 (Form 1065) | Partnership income, coded items, capital account |

## Configuration

Settings come from environment variables and the repository-root `.env` ([.env.example](.env.example)); [core/config.py](core/config.py) is the complete model.

### Models and parsing

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Model server URL (not Ollama's server-side `OLLAMA_HOST`) |
| `OLLAMA_TIMEOUT_S` / `OLLAMA_KEEP_ALIVE` | `180` / `30m` | Request timeout / model residency |
| `TEV_MODEL` | `tev1` | Classifier; `none` = heading-only |
| `TEV_MIN_CONFIDENCE` / `TEV_MAX_STATE_CHARS` | `0.5` / `3000` | Classifier acceptance threshold / input limit |
| `EXTRACTOR_MODEL` / `EXTRACTOR_NUM_CTX` | `qwen3.5:4b` / `8192` | Extraction model / context tokens |
| `EXTRACTOR_OUTPUT_TOKENS` | `2048` | Answer budget (`num_predict`); evidence gets the rest |
| `STRICT_GROUNDING` | `true` | Verify amounts and TINs against labels/positions; record `validation.sources` |
| `DOCLING_DEVICE` / `DOCLING_THREADS` | `auto` / `4` | `auto`, `cpu`, `cuda`, `mps` / CPU threads |
| `DOCLING_MAX_CONCURRENCY` | `1` | Concurrent conversions per process |
| `DOCLING_TIMEOUT_S` | `120` | Conversion timeout (s) |
| `DOCLING_TABLES` | `false` | TableFormer (the pipeline has its own table reader) |
| `DOCLING_WARMUP` | `true` | Small conversion at startup |
| `DOCLING_ARTIFACTS_PATH` | unset | Local Docling weights directory |

Offline Docling weights: `uv run main.py download-models --to models/docling`, then `DOCLING_ARTIFACTS_PATH=models/docling`.

### API and limits

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Business Partner API` | API title |
| `DATABASE_URL` | `sqlite:///<project-root>/tax_document_database.db` | API-key database |
| `ALLOW_KEY_BOOTSTRAP` | `false` | Allow unauthenticated creation of the first (admin) key |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | Log level / JSON logs |
| `MAX_UPLOAD_MB` / `MAX_PAGES` | `20` / `10` | Per-file upload limit / single-form route page limit |
| `BULK_MAX_FILES` / `BULK_MAX_PAGES` | `20` / `100` | Files per bulk request / pages per file |
| `BULK_MAX_TOTAL_MB` | `100` | Bulk body limit, counted as bytes arrive |
| `MAX_CONCURRENT_JOBS` / `MAX_QUEUED_JOBS` | `2` / `8` | Extract, bulk and library-upload jobs running / waiting; beyond → `503 busy` |
| `ASSISTANT_CONFIG` | `config/model_config.yml` | Assistant, embedding, library and business settings |
| `BUSINESS_SECRETS_KEY` | unset | Fernet key (base64) encrypting connector tokens at rest (variable name: `business.secrets_key_env`). Unset: a key is generated the first time a token or sign-in is stored and kept in `secrets.key` beside `business.database` (`data/secrets.key`; back it up with the database, and keep it out of shared storage). Set the variable to keep the key apart from the data: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Changing or losing the key makes stored tokens unreadable |

Rate limits (requests per key per window; window variable `*_RATE_SECONDS`, default `60`):

| Calls variable | Default | Routes |
|---|---|---|
| `PIPELINE_RATE_CALLS` | `30` | `extract` |
| `BULK_RATE_CALLS` | `10` | `extract/bulk` |
| `CLASSIFY_RATE_CALLS` | `120` | `classify` |
| `LIBRARY_RATE_CALLS` | `30` | Library uploads |
| `SEARCH_RATE_CALLS` | `120` | Library search |
| `ASSISTANT_RATE_CALLS` | `30` | Document assistant chat, partner chat and assistant runs together: one window per key shared by the three (`RateLimit("assistant")`) |

### model_config.yml

[config/model_config.yml](config/model_config.yml) configures `chat`, `embeddings`, `library`, `assistant` (validated by [agent/config.py](agent/config.py)) and `business` ([business/config.py](business/config.py)); the partner and role assistants use the same `chat` model. Providers: `ollama`, `openai`, `openrouter` (OpenAI-compatible API) and `anthropic` (Messages API, chat only), called over plain HTTP. Cloud API keys are read from the environment variable named by `api_key_env`, never from the file.

| Key | Default | Notes |
|---|---|---|
| `chat.model` | `qwen3.5:4b` (ollama) | `options` is merged into each request body; `max_completion_tokens` there replaces `max_tokens` |
| `embeddings.model` | `nomic-embed-text` (ollama) | Changing model or `dimensions` → `409 index_mismatch`: delete the library database (or set a new `library.database`) and re-add documents |
| `embeddings.query_prefix` / `document_prefix` | `"search_query: "` / `"search_document: "` | Set both to `""` for models without task prefixes |
| `library.database` / `library.files` | `data/library.db` / `data/files` | Relative to the project root |
| `library.chunk_chars` | `1500` | Max characters per chunk |
| `library.default_results` / `max_results` | `8` / `20` | Search result count |
| `assistant.max_tool_rounds` | `4` | Tool rounds before the document assistant must answer |
| `business.database` | `data/business.db` | Profile, answers, organized documents, assistants, approvals, notes, and the connectors' tables; relative to the project root. Workspace databases live in `databases/` beside it, a generated secrets key in `secrets.key` |
| `business.secrets_key_env` | `BUSINESS_SECRETS_KEY` | Environment variable holding the Fernet key |
| `business.public_url` | `http://localhost:8000` | Where the browser reaches the API; OAuth redirect URLs are built from it |
| `business.context.business` / `role` / `team` / `notes` | `4000` / `10000` / `1500` / `3000` | Characters per context layer of a role assistant |
| `business.assistant_prompt` | rules text | Leads every role assistant's business layer |
| `business.partner.max_tool_rounds` | `6` | Tool rounds per partner turn |
| `business.partner.system_prompt` | interviewer prompt | The partner's instructions |

Ollama's OpenAI-compatible API cannot set context size per request; if answers or excerpts are cut off, start Ollama with a larger `OLLAMA_CONTEXT_LENGTH` (e.g. `8192`).

## Development and testing

```sh
uv run pytest -m "not integration"     # unit/API tests, synthetic data, no models
uv run ruff check .                    # lint gate ([tool.ruff] in pyproject.toml); ruff is not a project dependency: uv tool install ruff
uv run pytest -m integration           # real Docling + Ollama; skipped when models are missing (check the skip count)
uv run python -m tests.evaluate        # accuracy report -> tests/reports/latest.json
node n8n/tests/code-nodes.test.mjs n8n/tax-document-intake.workflow.json n8n/tests/api-fixtures.json
uv run python -m scripts.licenses
```

Dashboard (in `web/`):

```sh
npm run typecheck
npm test         # Vitest unit and component tests
npm run e2e      # build + Playwright on tests.e2e.stack (fake models; set HF_HUB_CACHE if Docling weights are elsewhere)
```

After changing an API model or route, regenerate the dashboard types (both are checked by tests):

```sh
uv run python -m scripts.openapi       # web/src/api/openapi.json (tests/test_web.py)
cd web
npm run gen:api                        # web/src/api/schema.d.ts (npm test)
```

Full stack without GPUs or Ollama (real Docling, fake extraction/embedding/chat models, fresh data directory, keys printed as JSON):

```sh
uv run python -m tests.e2e.stack --api-port 8000 --models-port 11435
```

Accuracy on real documents: put redacted files in `tests/samples/redacted/` as `<name>.pdf` (or an image) with `<name>.forms.json`, a list of `{"document_type", "pages", "fields"}` in page order (`"status": "duplicate"` for repeated copies, `"fields": null` for non-form pages). The evaluator and `pytest -m integration` hold them to the scan accuracy bar. A field is scored when either side has a value: `0.00` against `null` is an error; `null`, `""`, `[]` and an unchecked box count as missing.

### Project layout

```text
Upload -> Docling parse/OCR -> split into forms -> classify
       -> read tables + pair labels/values -> LLM field mapping
       -> read checkboxes -> normalize and validate -> verify against labels/positions -> JSON
```

| Location | Responsibility |
|---|---|
| [main.py](main.py) | CLI: `serve`, `create-key`, `download-models`; `main:app` ASGI app |
| [api/](api/) | Routes, auth, rate limits, body limit, errors, dashboard serving ([api/web.py](api/web.py)) |
| [core/pipeline.py](core/pipeline.py) | Single-form and bulk orchestration |
| [core/parser.py](core/parser.py) | Docling lifecycle, conversion, page images |
| [core/segment.py](core/segment.py), [core/tev.py](core/tev.py) | Form boundaries, classification |
| [core/layout.py](core/layout.py), [core/tables.py](core/tables.py), [core/checkboxes.py](core/checkboxes.py) | Label/value pairing, table rows, checkboxes |
| [core/extractor.py](core/extractor.py) | Evidence chunks within the token budget, LLM mapping, answer merging |
| [core/grounding.py](core/grounding.py) | Amount/TIN verification, value sources |
| [core/flags.py](core/flags.py) | `Flag` and flag codes |
| [core/jobs.py](core/jobs.py) | Extraction job gate |
| [core/forms.py](core/forms.py), [core/schema.py](core/schema.py), [core/utils.py](core/utils.py) | Form definitions, response models, normalization |
| [core/auth.py](core/auth.py), [core/db.py](core/db.py), [core/models.py](core/models.py) | API-key storage |
| [library/](library/) | SQLite store, ingestion, hybrid search, files and page rendering, review rules |
| [agent/](agent/) | Assistant config, provider wire formats, the shared tool loop, document tools |
| [business/](business/) | Workspace store, question bank, context layers, workspace memory (records in the index), partner, assistant runner, hints, service; connectors and the workspace database app ([docs/CONNECTORS.md](docs/CONNECTORS.md)) |
| [web/](web/) | React dashboard |
| [scripts/](scripts/) | OpenAPI export, license listing |
| [tests/](tests/) | Unit/API, integration, evaluator, fixtures, fake model server, E2E stack |
| [n8n/](n8n/) | Optional intake and review workflow |

Dependency direction: `api -> business -> agent -> library -> core`. Request traces, test map and recipes (routes, tools, form types, flag codes, schema changes): [docs/DEVELOPING.md](docs/DEVELOPING.md). Dashboard structure and recipes: [web/README.md](web/README.md).

## Data handling and limitations

- Extraction routes (`/v1/documents/...`) store nothing; multipart handling may spool large uploads to temporary disk. Document evidence is sent to the configured Ollama server.
- The key database stores key hashes and metadata only.
- The workspace database (`data/business.db`) stores the business profile, interview answers, assistant specs, approvals (tool arguments and results as returned by the connector) and notes, plus the connectors' tables (tokens encrypted with `BUSINESS_SECRETS_KEY`, never returned or logged). A configured cloud chat provider receives the profile digest, notes, the screen state and tool results of the partner and assistants.
- Workspace databases are plain SQLite files under `data/databases/`, unencrypted; their contents reach the chat provider when an assistant queries them. The business profile, discovery answers and notes are also stored as index records in `data/library.db` (text and embeddings).
- Connectors added with a non-admin key reach only https servers on public addresses, and so do their OAuth flows; admin keys may also use http and local or private networks (e.g. a local n8n). The host is resolved again when connecting, so DNS rebinding is not prevented ([docs/CONNECTORS.md](docs/CONNECTORS.md#url-rule)).
- Write tools run under each assistant's policy; a tool its server marks read-only (`readOnlyHint`) always runs, so only connect servers you trust to label their tools.
- The library stores originals (`data/files/`) and, in `data/library.db`, forms with fields as read (full TINs), review decisions (reviewer key name, time), and chunks/embeddings (SSNs masked; names, addresses, amounts, EINs as printed). Both paths are gitignored; treat them and their backups as taxpayer data. A configured cloud chat provider receives questions and tool results (SSNs masked).
- Logs contain request and processing metadata; error messages and third-party diagnostics have not been audited for a strict no-sensitive-data guarantee.
- One worker per process; each process loads its own models and keeps its own rate-limit windows. Shared deployments need a shared limit or gateway policy. Terminate TLS at a reverse proxy and set a proxy body limit.
- Each running job holds its uploads in memory (up to `BULK_MAX_TOTAL_MB`); queued jobs spool to disk. Classification is not gated.
- Splitting is heuristic; pages without text are reported in `missing_pages`. Extraction noise can leave a real duplicate marked `ok`.
- Evidence token counts are estimated (digits one token each, other characters one per three, 10% margin), not tokenized.
- Synthetic test results do not establish accuracy on client documents.
- Export to tax or practice-management software is not implemented; map `fields` using `GET /v1/document-types`.

## Optional n8n integration

[n8n/README.md](n8n/README.md) covers the importable intake workflow (uploads, email attachments, Drive files, webhooks → bulk API), credentials, review routing, the `tax_document_log` table and notifications. The log stores extracted fields with TINs masked; failed execution records may retain document data. Configure retention and access in n8n separately.

## License and disclaimer

[DISCLAIMER.md](DISCLAIMER.md) · [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)
