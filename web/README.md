# Dashboard (`web/`)

React 19 + TypeScript (strict) single-page app of the business partner product ("Business Partner", the constant `PRODUCT` in [src/app/product.ts](src/app/product.ts)): the workspace dashboard, the partner chat, assistants and their approvals, the notes board, the business profile, the document library with its review workspace and document Q&A, the plugins page (the connector store) and settings. Built with Vite to `web/dist`, which the API serves at `/` ([api/web.py](../api/web.py)). Every API type is generated from [src/api/openapi.json](src/api/openapi.json).

## Commands

Run in `web/` (Node 20.19+ or 22.12+).

| Command | What it does |
|---|---|
| `npm ci` | Install the pinned dependencies (`package-lock.json`) |
| `npm run dev` | Vite dev server on :5173; `/v1`, `/auth`, `/api-keys`, `/health`, `/docs`, `/redoc`, `/openapi.json` are proxied to `API_URL` (default `http://127.0.0.1:8000`) |
| `npm run build` | `tsc -b` then `vite build` -> `web/dist` |
| `npm run preview` | Serve `web/dist` on :4173 with the same proxy |
| `npm run typecheck` | `tsc -b --noEmit` (app, config and E2E files) |
| `npm run gen:api` | `src/api/openapi.json` -> `src/api/schema.d.ts` (openapi-typescript) |
| `npm test` | Vitest unit and component tests (`src/**/*.test.{ts,tsx}`) |
| `npm run e2e` | `npm run build`, then Playwright against a real stack on fake models (see [E2E](#e2e)) |

A backend for local work without GPUs: `uv run python -m tests.e2e.stack --api-port 8000 --models-port 11435` from the repository root (prints an admin and a client key; see [docs/DEVELOPING.md](../docs/DEVELOPING.md#run-the-full-stack-locally-without-gpus)), then `npm run dev` and sign in with the client key.


Styling is plain CSS: CSS modules next to each component (`Button.module.css`), global tokens in `src/styles/tokens.css`. No UI kit, CSS framework, state library or chart library.

## Pages

| Path | Folder | Sidebar | What |
|---|---|---|---|
| `/` | `features/dashboard` | Workspace | Workspace summary (`GET /v1/workspace`) |
| `/partner` | `features/partner` | Workspace | Partner chat, interview progress, uploads for the partner (full bleed) |
| `/assistants`, `/assistants/:id` | `features/assistants` | Operations (expandable: active assistants) | List, create from a JSON spec; detail: status, run, context, write policy, spec |
| `/approvals` | `features/approvals` | Operations (badge: pending count) | Approvals queue and history |
| `/notes` | `features/notes` | Operations | Shared notes board by topic |
| `/profile` | `features/profile` | Knowledge (expandable: Departments, Roles, Tools, Information flows -> `/profile#<id>`) | Business profile, organized documents |
| `/knowledge` | `features/knowledge` | Knowledge | The index by source (`?view=all\|files\|workspace\|unused`, `?source=<id>` opens its passages), totals with what was never retrieved, and search over files and workspace records |
| `/documents`, `/documents/overview`, `/documents/:id` | `features/documents`, `features/overview`, `features/review` | Knowledge (Documents) | Library list and upload; library stats ("Overview" link on the list); review workspace (full bleed) |
| `/assistant` | `features/assistant` | Knowledge ("Ask documents") | Document Q&A (full bleed; also the slide-over panel) |
| `/connectors` | `features/connectors` | Connect ("Plugins") | Installed connectors and the store: search, category pills (Storage first; a listing also matches its `also_in`), then built-in apps, featured and the rest, or one list of matches. A card shows the `tagline`; the add dialog the setup text. A built-in listing asks for a name only and opens `/databases` |
| `/databases` | `features/databases` | Connect | The owner's workspace databases (`?db=<connector id>&table=<name>`): tables, a page of rows with add / edit / delete, CSV import and export, a SQL console (changes only with "Allow this statement to change data") |
| `/settings` | `features/settings` | Connect | Theme (light, dark, system), the key, key management |

## Add a page

1. Create `src/features/<name>/<Name>Page.tsx` (and `<Name>Page.module.css`) exporting the component; state and effects in the folder's `hooks.ts`.
2. Add one line to `pages` in [src/features/index.ts](src/features/index.ts):

   ```ts
   { path: "/clients", label: "Clients", icon: Users, component: ClientsPage, section: "Operations" },
   ```

Entries with a `section` (one of `SECTIONS`: Workspace, Operations, Knowledge, Connect) are listed in the sidebar under it, in array order; `icon` is a lucide-react icon. `useChildren` (a hook returning `{to, label}[]`) makes the entry expandable; `useBadge` (a hook returning a number or `undefined`) shows a count. `App.tsx` turns every entry into a route inside `Shell`; `fullBleed: true` renders it without the content padding and page scroll (partner, review and Ask documents manage their own scrolling). Start the page with `<PageHeader title=... />` and put content in `<Card>`s. Call `useScreenState({entity, detail})` with what the page shows and `track(...)` at its key interactions (see [Agentic UI](#agentic-ui)).

## Call a new endpoint

1. Change the API (models with `Field` descriptions), then from the repository root: `uv run python -m scripts.openapi` (writes `src/api/openapi.json`; `tests/test_web.py` fails while it is stale).
2. `npm run gen:api` (`src/api/schema.test.ts` fails while `schema.d.ts` is stale). Never edit `schema.d.ts` or declare API shapes by hand.
3. Add a hook to the resource's file in `src/api/` (or a new file):

   ```ts
   export function useClientSummary(client: string) {
     return useQuery({
       queryKey: ["clients", client],
       queryFn: () => unwrap(api.GET("/v1/library/clients/{client}", { params: { path: { client } } })),
     });
   }
   ```

   `unwrap` returns `data` from the `{data}` envelope or throws `ApiError {status, code, message, details}` built from the error envelope; `ok` is for 204 and binary responses (`parseAs: "blob"`). Paths, parameters and bodies are type-checked against `schema.d.ts`.
4. If a component needs the type by name, add an alias in `src/api/types.ts` (`Schemas["ClientSummary"]`; aliases go through openapi-fetch's `Readable`, so they match what the client returns).
5. Mutations invalidate what they change: library writes call `invalidateLibrary` (document lists and stats); review writes also refresh the form and its document (`review.ts`). The business resources:

   | File | Query keys | Writes refetch |
   |---|---|---|
   | `business.ts` | `["workspace"]`, `["business", "profile" \| "interview" \| "documents" \| "notes"]` | profile save: sets the profile, workspace; partner reply: sets the interview, then `profile_changed` -> profile and organized documents, `assistants_changed` -> assistants, either -> workspace; organize -> organized documents; note -> notes |
   | `assistants.ts` | `["assistants"]`, `["assistants", id]`, `["assistants", id, "context"]`, `["assistant-schema"]` (session), `["approvals", status \| "all"]` | create, update, status, delete -> assistants and workspace; run -> approvals, workspace, notes; decision -> approvals, assistants, workspace |
   | `connectors.ts` | `["connector-catalog"]` (session), `["connectors"]`, `["connectors", id, "tools"]` | add, remove -> connectors and workspace; check -> also that connector's tools; OAuth start -> `window.location.assign(authorize_url)` |
   | `knowledge.ts` | `["knowledge", "map", filter]`, `["knowledge", "passages", id, limit]` | search -> everything under `["knowledge"]` (hits count as retrieved); library uploads and deletes (`invalidateLibrary`) too |
   | `databases.ts` | `["databases", id, "tables"]`, `["databases", id, "rows", table, offset]` | every write (table, row, import, SQL) -> everything under `["databases", id]` |

## How things run

### Requests and auth

`api/client.ts` creates one openapi-fetch client. Its middleware adds `X-API-Key` (set by `setApiKey`) to every request, and on a 401 calls the handler registered by `AuthProvider`, which clears the key, empties the query cache and shows the sign-in screen with a notice. Sign-in calls `GET /auth/me` with the entered key; the key is kept in `sessionStorage["tda.key"]`, or `localStorage` with "Remember on this device". On load, a stored key is verified with `/auth/me` before anything renders. The middleware also reports every non-2xx response to the listener set with `setFailureListener` (the agentic UI's `error` events). Query defaults (`App.tsx`): 15 s stale time, no refetch on focus, no retry of 4xx errors.

### Documents and upload

`DocumentsPage` keeps its filters (`q`, `client`, `tax_year`, `document_type`, `review_status`, `offset`) in the URL, so the overview's links (`/documents/overview`, linked as "Overview" from the list's header), the top bar search (`/documents?q=`) and reloads land on the same list; `?upload=1` opens the upload dialog. The list is `GET /v1/library/documents` (25 per page), its counts come with each row (`forms_pending`, `open_flags`, `review_status`). Upload sends the files one after another (`POST /v1/library/documents`, multipart: `file`, `client`, `tax_year`; `useUploadDocument` sends `extract=false` only when called with `extract: false`, as the partner page does; the API's default is `true`); each row shows its own result or error message (409/413/415/422/503 bodies). The queue (items, states, `start`) is `useUploadQueue` in [features/documents/hooks.ts](src/features/documents/hooks.ts); `UploadDialog` renders it. Short form names (`W-2`) come from `GET /v1/document-types` (`name`), fetched once per session (`useTypeName`).

### Review workspace

`/documents/:id?form=<form id>&page=<n>` ([features/review](src/features/review)). State and effects are hooks in [hooks.ts](src/features/review/hooks.ts), which `ReviewPage` and `FormReview` render: `useWorkspace` (selected form, page, check and overlays from the URL; steps 1 and 5), `useRowSelection` (keeps a visible row selected and in view; `move`), `useDecide` (decisions, approval, the edited field and row errors; steps 6 and 7), `useReviewShortcuts` (the shortcuts below).

1. `ReviewPage` loads the document (`GET /v1/library/documents/{id}`: pages with sizes, forms). Without `?form`, it opens the extracted form containing `?page` (assistant citations), else the first extracted form. Duplicate and unsupported forms show an explanation instead of checks.
2. `useForm` loads `GET /v1/library/forms/{id}`: checks, form flags, progress. `FormReview` filters them (Flagged: has flags; Unchecked: no decision; All), defaulting to Flagged when the form has open flags.
3. Pages: `usePageImage` fetches `GET .../pages/{n}?width=1600` as a blob (the route needs the key header, so no `<img src>` to the API), caches it for the session and hands out an object URL. The viewer and every crop use the same cached image.
4. Geometry ([geometry.ts](src/features/review/geometry.ts)): `ValueSource.box` is `[left, top, right, bottom]` on a page 1000 units wide (both axes; a page is `1000 * height / width` units tall). `boxStyle` places overlays in percent of the page, so they follow the zoom; `cropStyle` sizes the page as a background image so that the box plus 12 units of padding fills at most 200 x 36 px. Checks without a source (a value not found in the page text, a removed value, an empty box) show "Not located".
5. Selecting a check (click, `j`/`k`/arrows, or a box on the page) switches the viewer to the source page and scrolls both the row and the box into view.
6. Decisions: `PUT /v1/library/forms/{id}/reviews/{field}` with `confirmed`, `corrected` (value from the kind-aware editor: select for checkboxes, choices and months, date input for dates, text otherwise; [values.ts](src/features/review/values.ts) catches obvious typos, the API parses and answers `422 invalid_value` with the message shown in the row) or `rejected`; Undo is `DELETE` on the same path. `useReviewField` shows the decision in the cached form at once (reviewer blank) and puts the form back if the request fails (the row shows the error); the returned check then replaces the row, and the form, document, list and stats queries refetch. After a decision the next visible row is selected.
7. Approve is disabled, with the reason, while a flagged field has no decision; `POST .../approve` answering `409 review_incomplete` shows the message and selects the first field of `details.undecided`. An approved form shows who approved it and a Reopen button (`POST .../reopen`).

Shortcuts (ignored while typing): `j`/`k` or arrows move, `c` confirm, `e` correct, `r` reject, `u` undo, `Esc` cancels an edit. `Enter` saves a correction.

### Shell and sidebar

`Shell` ([app/Shell.tsx](src/app/Shell.tsx)): `Sidebar`, then a top bar with the business name (`business_name` from `GET /v1/workspace`, "Your business" until it loads), the document search, "Ask the partner" (not on `/partner`), "Ask documents" (opens the document assistant panel; not on `/assistant`) and the signed-in key (name, admin or client, sign out); below it `HintsBar` and the page.

`Sidebar` ([app/Sidebar.tsx](src/app/Sidebar.tsx)) renders `SECTIONS` with their `pages` entries: a muted section label, then per entry the icon, label, count badge (`useBadge`) and, for `useChildren` entries, a chevron button ("Expand <label>" / "Collapse <label>"; open by default while the entry's route is active). The active entry (`useMatch`, prefix match except `/`) is a filled pill (`--nav-active`). The collapse button turns it into a 68 px icon rail (`data-collapsed`, kept in `localStorage["tda.sidebar.collapsed"]` as `1`/`0`): labels stay as accessible names and `title` tooltips, section labels are cut to 5 characters, chevrons and children are hidden, badges sit on the icon. At the bottom "Browse plugins" links to `/connectors`. On the sidebar's right edge a vertical sun/moon pill (`radiogroup` "Theme", radios "Light" and "Dark") sets the theme; `system` is chosen in Settings (then neither radio is checked).

### Agentic UI

`AgenticProvider` ([app/agentic.tsx](src/app/agentic.tsx), inside the router, around the routes) keeps the last 50 `UiEvent`s (`{type, page, target, detail, at}`), oldest first:

| Event | When | `target` / `detail` |
|---|---|---|
| `navigate` | the route path changes (not query or hash) | `null` |
| `select`, `action` | a page calls `track(type, target, detail)` | e.g. `filter:pending`, `approval:<id>` `{approve, always, tool}`, `connector:add` `{listing, transport, auth}`, `partner:send`, `assistant:<id>:run` |
| `error` | any API response that is not 2xx, except the hints route | `"<METHOD> <path>"`, `{status}` |
| `idle` | 45 s without `keydown`, `pointerdown` or `wheel` (once, re-armed by input) | `{seconds: 45}` |

`useScreenState({entity, detail})` declares what the page shows (cleared on unmount); `uiState()` is `{page: <path>, entity, detail}` (`UiState`). Pages declare e.g. the review page `{entity: {kind: "document", id, title}, detail: {form, page, field}}`, an assistant `{entity: {kind: "assistant", ...}, detail: {status}}`, the store `{entity: <listing being added>, detail: {q, category, manual}}`.

Hints: 600 ms after a navigation, an idle event or a `track` call (a later one restarts the wait), `POST /v1/workspace/hints` with `{state: uiState(), events}`; only the latest request's answer is shown (each request, scheduled or not yet sent, makes answers to earlier ones stale), failures are ignored, and a navigation clears the hints on screen. `HintsBar` ([app/HintsBar.tsx](src/app/HintsBar.tsx)) shows the first (most relevant) hint in one row under the top bar (icon by `tone`, title, body, the `action` as a link, which is tracked as `hint:<id>`) with a dismiss button, and the others behind "+n more" / "Show less"; dismissed ids are kept per signed-in key in `localStorage["tda.hints.dismissed.<key id>"]` (`dismissedKey`; the last 200; storage failures ignored) and filtered out of every later answer.

Ask the partner: the top bar button calls `askPartner()`, which stores the current `uiState()` as `attached` and opens `/partner`; the partner page shows "Sending with the screen you came from: <page>" and its next message sends `attached` as `ui_state` (then cleared). Every other partner message sends the partner page's own `uiState()`.

### Dashboard

`/` ([features/dashboard](src/features/dashboard)): `GET /v1/workspace` (`useWorkspaceSummary`, shared with the top bar and the approvals badge). Tiles (links): interview `answered / total`, labelled "questions covered" (a question counts when answered or when the profile already has what it asks; `/partner`), profile `profile_fields / profile_total` (`/profile`), documents `organized_documents / documents` (`/profile#documents`), pending approvals (`/approvals`). Cards: interview progress per area; assistants by status (active, draft, paused) and connectors by status (connected, needs_auth, error, untested), labels and tones from [lib/status.ts](src/lib/status.ts); "Recommended connectors" (`recommended_connectors`) with Add -> `/connectors?add=<listing id>` (tracked `recommended:<id>`).

### Partner

`/partner` ([features/partner](src/features/partner); `hooks.ts`: `usePartnerConversation`, `usePartnerUploads`, `usePartnerComposer`, `useDropZone`).

1. The conversation lives in the page (lost on leaving it). Sending (Enter; Shift+Enter breaks the line; "Start the interview" sends a first message) appends the owner's message and posts the conversation: `POST /v1/partner/chat` `{messages, ui_state}` (`usePartnerChat`), where `messages` is the newest `MAX_TURNS` (50, the API's limit) turns starting at an owner turn (`recent`); the profile and interview reach the partner in the server's own state message. Stop aborts the request ("Stopped." with Retry); a failure shows its message with Retry; "New chat" clears it and drops a late reply.
2. Answers render with the document assistant's `AssistantMessage` (Markdown, citations, sources, tool line, copy); pending shows `Thinking` ("Thinking…").
3. The reply's `interview` replaces the cached `GET /v1/business/interview`; `profile_changed` and `assistants_changed` refetch as in [Call a new endpoint](#call-a-new-endpoint), so the top bar's business name, the sidebar's assistants and the dashboard follow.
4. Uploads: files dropped anywhere on the page (an overlay shows while dragging files) or picked with "+" ("Upload documents") are stored one after another with `POST /v1/library/documents` (multipart, `extract=false`); a chip per file (by upload, so equal names stay apart) shows "Uploading <name>…" or the error (dismissable). Once no upload is running and the partner is not answering, one message lists them: `I uploaded 2 documents for you to organize into the business profile:\n- <title> (document id <id>)\n…` (`describeUploads`).
5. Beside the chat (hidden under 1100 px): `answered / total` ("covered"), progress per area, and the next questions (`next`); clicking one sends `Ask me this next: <question>` (its `purpose` is the tooltip).

### Business profile

`/profile#<section>` ([features/profile](src/features/profile)): `GET /v1/business/profile`. Sections (anchors, also the page's table of contents): `overview`, `departments`, `roles`, `tools`, `flows`, `financials`, `compliance`, `documents`; the field lists are data in [sections.ts](src/features/profile/sections.ts) (kinds: `text`, `optional` (empty -> `null`), `textarea`, `lines` (one list item per line), `number` (empty -> `null`), `select`). One section is edited at a time ("Edit", then Save or Cancel); Save sends the whole profile with that section replaced: `PUT /v1/business/profile` (`useSaveProfile`; errors show in the section). List sections edit every item at once (Add / Remove <item>). A tool whose `listing_id` is a store listing that is not installed shows "Connect" -> `/connectors?add=<listing id>`; installed, "Connected". The hash scrolls to its section once the profile is loaded.

Organized documents: `GET /v1/business/documents`; Edit on a row turns department (a select of the profile's departments) and kind into inputs; Save sends `PUT /v1/business/documents/{document_id}` `{department, kind, summary}` (summary unchanged).

### Assistants

`/assistants` ([features/assistants](src/features/assistants)): `GET /v1/assistants` (name, role, department, status, connector count, created by). "New assistant" opens a JSON editor starting from `TEMPLATE` ("Use template" restores it). [specSchema.ts](src/features/assistants/specSchema.ts) checks the text on every change against `GET /v1/assistants/schema` (fetched once per session): `parseSpec` reports invalid JSON, then `validate` the subset of JSON Schema the spec's schema uses (`type`, `enum`, `properties`, `required`, `additionalProperties` false or a schema, `items`, `anyOf`, local `$ref`, `minLength`/`maxLength`, `minimum`/`maximum`); errors are listed under the editor as `<path> <message>` (e.g. `policy.tools.crm/send must be one of "auto", "ask", "deny"`). Create is enabled only for a valid spec: `POST /v1/assistants`, then the new assistant's page opens. The sidebar lists active assistants under Assistants (`useActiveAssistantLinks`).

`/assistants/:id`: `GET /v1/assistants/{id}`.

- Status: Draft / Active / Paused -> `PUT /v1/assistants/{id}/status`. Delete (with confirmation) -> `DELETE`.
- Run a task (only while active; Ctrl+Enter; not while a run is in progress): `POST /v1/assistants/{id}/run` `{messages: [{role: "user", content}]}`; the answer renders with `AssistantMessage`, then each `ToolRun`: `<connector>/<tool>`, Read or Write, outcome (Ran, Waiting for approval with "Review in approvals" -> `/approvals`, Denied, Failed), arguments and result behind a disclosure.
- What it sees: `GET /v1/assistants/{id}/context`: each layer (name, length, text behind a disclosure), the offered tools, total characters.
- Write policy: default mode (Auto / Ask / Deny) and a mode per write tool of its connectors (`GET /v1/connectors/{id}/tools` for each id in `connectors`, `read_only: false` only; "Default (<mode>)" removes the override; overrides for tools no longer offered are listed so they can be cleared). Save policy sends the spec with the new `policy`: `PUT /v1/assistants/{id}`.
- Spec: the JSON editor on the saved spec, checked as above; Save spec -> `PUT /v1/assistants/{id}`. The policy editor restarts when the saved policy changes and the spec editor when the saved spec changes (keyed on their JSON), so a status change or saving one editor keeps unsaved edits in the other.

### Approvals

`/approvals?status=<pending|all|executing|executed|rejected|failed>` ([features/approvals](src/features/approvals)), default `pending`: `GET /v1/approvals?status=` (no `status` for All), pending sorted first. Each card: assistant (link), `<connector>/<tool>`, age, status, the assistant's reason, arguments as indented JSON. Pending cards: optional note, Reject, Always allow, Approve -> `POST /v1/approvals/{id}/decision` `{approve, always, note}`; the list refetches after every decision, also after an error (a `409 already_decided` means it was decided elsewhere); the toast follows the returned status (`Ran <tool>` (+ `; <assistant> may now use it without asking` for always), `<tool> failed: <result>`, `Rejected <tool>`). Decided cards show who decided, when, the note and the result. The sidebar badge is `pending_approvals` from the workspace summary.

### Notes

`/notes?topic=` ([features/notes](src/features/notes)): `GET /v1/business/notes` (all topics, newest first) grouped into one card per topic, compared case-insensitively as in the API (shown with the newest note's spelling; topics in order of their newest note); topic pills narrow it to one. "Post a note" (topic with the known topics as suggestions, text): `POST /v1/business/notes` as the owner.

### Plugins

`/connectors` ([features/connectors](src/features/connectors)): `GET /v1/connectors` (installed) and `GET /v1/connectors/catalog` (the store, fetched once per session).

- Installed: name, server (URL or command and args), status, tool count, last check. Actions: Sign in (OAuth connectors with status `needs_auth` or no stored secret), Check -> `POST /v1/connectors/{id}/check` (toast with the result), Tools -> `GET /v1/connectors/{id}/tools` in a row below (Read-only / Write badges), Remove (with confirmation) -> `DELETE`.
- Store: Featured row (hidden while searching or filtering), search (client-side over name, publisher, description, capabilities), category select; cards with name, publisher, Add (or "Added" when a connector has its `listing_id`), description (three lines; the full text with setup steps is in the add dialog), capabilities, category, availability and a docs link.
- Add from a listing: `?add=<listing id>` (Add sets it; the dashboard, profile and hints link to it; an unknown id shows a warning) opens a dialog prefilled from the listing: name, the server URL only when the listing has none, and the token: "API key or token" (required) for `bearer`, "OAuth client (client_id:client_secret), if the provider requires one" (optional; providers without dynamic client registration) for `oauth`.
- "Add manually": name, transport (Streamable HTTP, SSE, stdio), server URL or command and arguments (one per line; stdio is admin keys only and has no authentication: `auth` is forced to `none`), authentication (none, bearer, OAuth) and the token field as above. The token lives only in the dialog's state and the request: `useAddConnector` has `gcTime: 0`, so the mutation (and its body) leaves the query client's cache once the dialog closes.
- Both send `POST /v1/connectors` `{listing_id, name, transport, url, command, args, auth, token}` (`token` `null` when empty or `auth` is `none`); the API checks it, and the toast says "Added <name>" or the check's error; errors (e.g. `403` for stdio with a client key) show in the dialog. An `oauth` connector instead stays in the dialog with "Sign in": `POST /v1/connectors/{id}/oauth`, then the browser goes to `authorize_url`; refusals (`422 invalid_connector`, `502 connector_failed`) show their message.
- Back from the provider: `?connected=<id>` shows "Signed in: the connector is ready"; `?oauth_error=<code>` shows an alert (`expired`, `no_code`, `access_denied` have their own wording); both parameters are then removed.

### Ask documents (document assistant)


`AssistantProvider` ([app/assistant.tsx](src/app/assistant.tsx)) holds one in-memory conversation and scope shared by the slide-over (`AssistantPanel`, opened from the top bar's "Ask documents" or "Ask about this document") and `/assistant` (`AssistantPage`, "Ask documents" in the sidebar); both render `Chat` from [features/assistant](src/features/assistant):

| File | Part |
|---|---|
| `Chat.tsx` | Empty state (page: greeting, composer, suggestion pills, "Needs review"; panel: intro and suggestion list), conversation thread, composer dock |
| `Composer.tsx` | Question box, "+" menu (upload, attach), scope pills or document chips, send / stop |
| `hooks.ts` | `useComposer`: the question, auto-grow, Enter to send, upload and attach (what `Composer` renders) |
| `Mark.tsx` | The assistant mark: an inline-SVG twisted (Möbius) loop, one ribbon segment drawn three times at 120° (hues `--mark-from` → `--mark-to`, turning to `--mark-shade` where each end tucks under the next; per-instance ids via `useId`); `busy` adds a 2.8 s sheen and breathing, static under reduced motion. Used for the nav item, Assistant buttons, greeting, answer avatar and the pending row |
| `Message.tsx` | User bubble, answer (Markdown, citations, sources, tool line, copy), pending and failure rows; `Thinking` takes a fixed `label` and `Failure` another chat's `{error, stopped, retry}` (the partner page and the run panel reuse them) |
| `chatUtils.ts`, `markdown.ts`, `citations.ts` | `greeting`, `isNearBottom`, `describeTool`; the Markdown subset; `[n]` citations |

1. Scope: `{client?, tax_year?, documents[]}`, sent as `toFilters(scope)` (`client`, `tax_year`, `document_ids`). The composer shows "All clients" / "Any year" pills (clients from `GET /v1/library/stats`, the last eight years) or, once documents are attached, a chip per document; attaching clears client and year, since all filters must match. Opening the panel on a review page scopes it to that document (the page registers it with `setCurrentDocument`).
2. "+" menu: "Upload a document" uploads one file with `useUploadDocument` (the scope's client and year; a chip shows "Uploading…", errors show in the composer) and attaches the result; "Attach a library document" searches `GET /v1/library/documents?q=` (8 results; Enter picks the first) and attaches the pick. Menus are `components/Menu.tsx`: arrows, Home and End move, Esc closes and refocuses the trigger, Tab or a click outside closes.
3. Sending (Enter; Shift+Enter breaks the line; the textarea grows to 8 rows) appends the question and posts the whole conversation and the scope to `POST /v1/assistant/chat` (the API is stateless). While it runs, Send becomes Stop (aborts the request; "Stopped." with Retry) and the thread shows "Searching documents…" ("Reading <title>…" with one attached document) with the elapsed seconds after 5 s: the API answers once, so the wording follows the scope, not live tool progress. A failure shows its message with Retry, which resends the conversation.
4. An answer is parsed by `parseMarkdown` (paragraphs, headings, lists, fenced code, bold, inline code; rendered as elements, never as HTML). `[n]` becomes a citation chip (only numbers present in `sources`; hover or focus shows title and page). Below: "Sources" cards for the cited excerpts (title, form name, page), the other retrieved excerpts behind "+n more retrieved", the tool line (`describeTool`, e.g. `Searched “wages” · Read w2`; expands to each call's name and arguments) and Copy. A citation or source opens `/documents/<document_id>?page=<page_number>`.
5. The thread keeps the newest message in view unless the user scrolled more than 80 px up (`isNearBottom`, also on resize); sending always returns to the end. "New chat" (page top-right, panel header; shown once there is a conversation) aborts a running request and clears the turns; a late reply is dropped.
6. Empty page: "Needs review" lists up to three documents from `GET /v1/library/documents?review_status=pending` with open flags; a card asks "What still needs review in this document?" scoped to it. Suggestions switch to document questions while documents are attached.

## Theming

Tokens are CSS custom properties in [src/styles/tokens.css](src/styles/tokens.css): `:root` is the light theme, `:root[data-theme="dark"]` overrides the colours. `ThemeProvider` stores the choice (`light` default, `dark`, `system`) in `localStorage["tda.theme"]` (failures ignored) and sets `data-theme` on `<html>`, following `prefers-color-scheme` while on `system`; the inline script in `index.html` does the same before the first paint. The sidebar's sun/moon toggle sets `light` or `dark`; Settings (Appearance) also offers `system`.

| Group | Tokens |
|---|---|
| Type | `--font` (Inter Variable), `--mono`, `--fs-xs` 11.5 / `--fs-sm` 12.5 / `--fs-md` 14 (base) / `--fs-lg` 16 / `--fs-xl` 20 / `--fs-2xl` 26 px; `--fs-chat` 15 (messages, composer), `--fs-display` 28 (assistant greeting) |
| Spacing | `--s-1` 4, `--s-2` 8, `--s-3` 12, `--s-4` 16, `--s-5` 20, `--s-6` 24, `--s-8` 32, `--s-10` 40 px |
| Shape | `--r-sm` 4, `--r` 6, `--r-lg` 8, `--r-xl` 12, `--r-2xl` 18 px, `--r-full`; `--shadow-xs`, `--shadow-sm`, `--shadow-lg`, `--shadow-popover` (menus), `--shadow-composer` / `--shadow-composer-focus`; `--control-h` 32 px |
| Surfaces | `--bg`, `--surface`, `--surface-2`, `--surface-hover`, `--surface-sunken`, `--border`, `--border-strong`, `--overlay`, `--bubble` (the user's chat messages) |
| Text | `--text`, `--text-2`, `--text-3` (4.5:1 or more on every surface token in both themes), `--text-on-accent` |
| Accent | `--accent`, `--accent-hover`, `--accent-text`, `--accent-soft`, `--accent-border`, `--focus-ring` |
| States | `--success`, `--warning`, `--danger`, `--info`, each with `-soft` and `-border` |
| Page overlays | `--box`, `--box-flag`, `--box-done`, `--box-selected`, each with `-fill` |
| Layout | `--sidebar` 240 px, `--sidebar-rail` 68 px (collapsed), `--topbar` 56 px |
| Sidebar | `--nav-bg` (light white, dark `#0b0e1d` navy), `--nav-border`, `--nav-text`, `--nav-text-muted` (section labels, children), `--nav-hover`, `--nav-active` / `--nav-active-text` (the active pill: light `#0c0e16` on white text, dark the lighter navy `#252a48`), `--nav-toggle-on` / `--nav-toggle-on-text` (the selected sun/moon) |

Statuses map to a label and tone in [src/lib/status.ts](src/lib/status.ts) (assistants: active `success`, draft `neutral`, paused `warning`; connectors: connected `success`, needs_auth `warning`, error `danger`, untested `neutral`; approvals: pending `warning`, executing ("Running") `info`, executed `success`, rejected `neutral`, failed `danger`; tool runs: ran `success`, pending_approval `warning`, denied and failed `danger`). Tones map to meaning in [src/lib/flags.ts](src/lib/flags.ts): removed values (`not_printed`, `wrong_label`, `unparseable`, `no_output`) are `danger`, values to double-check `warning`, form-level facts `info`; decisions are confirmed `success`, corrected `accent`, rejected `danger`. Amounts use `.num` (tabular numerals).

## Tests

Unit and component tests (Vitest, `npm test`). Tests run in Node; a component test starts with `// @vitest-environment jsdom` and renders with Testing Library. [src/test/api.ts](src/test/api.ts) (the setup file in `vite.config.ts`) fakes the API behind `fetch` for those: `serve(handler)` answers every request (`json`, `apiError`, `deferred` to hold one open, `sentForm` for multipart bodies) and adds what jsdom lacks (`<dialog>` methods, `scrollIntoView`, object URLs); [src/test/fixtures.ts](src/test/fixtures.ts) has a W-2 `FormDetail`, a `DocumentDetail`, the assistant spec's JSON Schema as the API returns it (`specSchema`), and `workspace`, `assistant`, `listing`, `connector`, `approval` builders. [src/test/app.tsx](src/test/app.tsx) `renderApp(path, routes)` renders the signed-in app (providers, `MemoryRouter` at `path`, `Routed`) on the fake API: `routes(route, sent)` answers `"<METHOD> <path>"` (undefined falls through to defaults for `/auth/me`, `/v1/workspace`, hints (none), assistants (none), the interview and document types; anything else is a 404); `sent(route)` lists the requests with their JSON bodies.

| File | Covers |
|---|---|
| `src/features/review/values.test.ts` | Corrected-value parsing per kind, editor start values |
| `src/features/review/geometry.test.ts` | Box placement in percent, crops with padding and clamping |
| `src/features/assistant/citations.test.ts` | `[n]` / `[1, 2]` citations, unknown numbers left as text |
| `src/features/assistant/markdown.test.ts` | Paragraphs, lists with continuations, headings, fenced code, bold and code spans, HTML kept as text |
| `src/features/assistant/chatUtils.test.ts` | Greeting by hour, scroll stickiness threshold, tool-call wording |
| `src/api/schema.test.ts` | `schema.d.ts` is current with `openapi.json` |
| `src/filenames.test.ts` | No two modules differ only in case (Windows and macOS ignore case, so `./Chat` could load `chat.ts`) |
| `src/features/review/FormReview.test.tsx` | Keyboard flow: move, confirm, correct (Enter), reject, undo; Approve disabled with its reason until every flag is decided, then approved; a refused approval selects the field it names |
| `src/api/review.test.tsx` | `useReviewField`: the decision shows at once, then the API's check; a refused decision puts the form back |
| `src/features/documents/UploadDialog.test.tsx` | Upload dialog: queued, remove, one upload at a time, uploading, done (forms and flags, Review link), failed (API message), retry of failed files only, client and year sent |
| `src/features/assistants/specSchema.test.ts` | Spec validation: template and minimal spec valid; invalid JSON; required, types, lengths, ranges, unknown fields; `$ref`, `anyOf`, `items`, enums, `additionalProperties` schemas, with paths |
| `src/app/Sidebar.test.tsx` | Sections and item order, active item, pending badge, expandable groups (active assistants only, profile sections), business and key name; collapse to the icon rail and back (remembered); theme toggle |
| `src/app/HintsBar.test.tsx` | Hints requested after each navigation with the screen state and events; a dismissed hint is stored and stays hidden in later answers; the first hint shows, the rest behind "+n more"; tracked actions and API errors become events and trigger a request |
| `src/features/assistants/AssistantsPage.test.tsx` | Create flow: template, invalid JSON and schema errors inline, Create disabled until valid, the POSTed spec, the new assistant's page (status, context); policy editor (write tools only, per-tool override saved in the spec) and run panel (outcome per tool run, approvals link); Ctrl+Enter during a run does not start a second one |
| `src/features/approvals/ApprovalsPage.test.tsx` | Pending cards (arguments, reason); Always allow and Reject with a note send their decisions; the list empties; history shows who decided |
| `src/features/connectors/ConnectorsPage.test.tsx` | `?add=` opens the listing's dialog; bearer token required and sent; the installed row; manual add (SSE), stdio (no auth, args per line, API refusal shown), OAuth listing (optional client, then Sign in) |
| `src/features/partner/PartnerPage.test.tsx` | "Ask the partner" attaches the previous screen's `ui_state`, later messages send the partner page's; the conversation is sent (at most the newest 50 turns, starting with the owner's: `recent`); `profile_changed` refetches the workspace (business name); uploads use `extract=false`, then one message lists ids and titles; a next question asks |
| `src/app/SignIn.test.tsx` | Sign-in: a refused key shows the reason and is not stored; a valid key is sent and remembered; a later 401 signs out with a notice and empties the cache; a stored key is checked first |

### E2E

`npm run e2e` builds, then [e2e/global-setup.ts](e2e/global-setup.ts) runs `uv run --no-sync python -m tests.e2e.stack` from the repository root with a fresh temporary data directory (API on `E2E_API_PORT`, default 8765; fake models on `E2E_MODELS_PORT`, default the next port), serving the new `web/dist`, waits for `/health` to report `ok` (Docling loads first) and stops it after the run (its process group; `taskkill /T` on Windows). It sets `HF_HUB_OFFLINE=1` unless the environment says otherwise; set `HF_HUB_CACHE` (or `DOCLING_ARTIFACTS_PATH`) when Docling's weights are not in the default cache. Playwright is pinned to 1.63.0 to match the installed Chromium; `npx playwright install chromium` provides one elsewhere.

[e2e/dashboard.spec.ts](e2e/dashboard.spec.ts) is one test in steps: wrong key refused and sign-in (lands on the Dashboard); Documents, upload `tests/samples/w2.pdf` and `stack.pdf` for a client; document overview (`/documents/overview`) counts (2 documents, 4 forms, 4 awaiting review, 8 open flags); W-2 review: Approve disabled with its reason, confirm, correct (Enter), reject and undo by keyboard, approve; dark theme from the sidebar toggle kept after reload; document assistant panel ("Ask documents"): an answer with a search tool line, a citation, and a source that opens the document at its page; Ask documents page: the same conversation, a `list_documents` question sent with Enter, New chat back to the greeting; delete with confirmation. The business pages are covered by the component tests only.

## Dependencies

| Package | Version | Use |
|---|---|---|
| react, react-dom | 19.2.9 | UI |
| react-router | 7.18.4 | Routing (library mode: `BrowserRouter`, `Routes`) |
| @tanstack/react-query | 5.104.1 | Server state: caching, invalidation, mutations |
| openapi-fetch | 0.17.0 | Typed fetch client over `schema.d.ts` |
| lucide-react | 1.54.0 | Icons |
| @fontsource-variable/inter | 5.3.0 | Inter variable font, bundled |
| vite, @vitejs/plugin-react | 7.3.7, 5.2.0 | Dev server, build |
| typescript | 5.9.3 | Type checking (openapi-typescript 7 supports TypeScript 5) |
| openapi-typescript | 7.13.0 | `npm run gen:api` |
| vitest | 5.0.5 | Unit and component tests |
| @testing-library/react, @testing-library/dom, @testing-library/user-event | 16.3.3, 10.4.2, 14.6.8 | Component tests (render, queries, keyboard and pointer events; `dom` is `react`'s peer) |
| jsdom | 30.1.3 | DOM for component tests |
| @playwright/test | 1.63.0 | E2E |
| @types/react, @types/react-dom, @types/node | 19.2.18, 19.2.7, 22.20.5 | Types (Node types for config, E2E and the schema test) |
