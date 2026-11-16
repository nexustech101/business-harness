# Connectors

Connectors (MCP servers and built-in apps): the store catalog, how an installed connector is stored, and how each operation runs. Routes: [api/routes/connectors.py](../api/routes/connectors.py) (`/v1/connectors`). Code: [business/connectors.py](../business/connectors.py) (`ConnectorHub`: store, orchestration), [business/mcp_client.py](../business/mcp_client.py) (network: `mcp` SDK sessions, results, OAuth steps), [business/catalog.py](../business/catalog.py) (store listings). Tests: [tests/test_connectors.py](../tests/test_connectors.py).

## Interface (what the rest of the app calls)

| Call | Returns / raises |
|---|---|
| `ConnectorHub(database, secrets_key, public_url, key_file=None)` | `secrets_key`: Fernet key (bytes) or None; `key_file`: where a key is generated and kept when `secrets_key` is None (see [Storage](#storage)); `public_url`: browser-facing API base, for the OAuth redirect `<public_url>/v1/connectors/oauth/callback` |
| `catalog()` | `list[ConnectorListing]`: built-in apps, then featured, then store order |
| `database(owner, id)` | The `DatabaseApp` when `id` is one of the owner's workspace databases, else `None` |
| `list(owner)`, `get(owner, id)` | `ConnectorInfo` (oldest first) / `None` |
| `await add(owner, ConnectorCreate, admin)` | `ConnectorInfo` after a check; `NotAllowed` (403) stdio without admin; `InvalidConnector` (422) |
| `remove(owner, id)` | `bool`; a built-in database's file is deleted with it |
| `await check(owner, id)` | `ConnectorInfo` with fresh `status`, `error`, `tool_count`, `checked_at`; `None` when unknown |
| `await tools(owner, ids)` | `list[ConnectorTool]` of the listed connectors that connect; unknown or failing ones skipped (their status is recorded) |
| `await call(owner, id, tool, arguments)` | `ToolResult(text, is_error)`; never raises for connection or tool errors |
| `await start_oauth(owner, id)` | `OAuthStart(authorize_url)`; `None` when unknown; `InvalidConnector` (422) when not an OAuth connector or when a URL the flow would fetch breaks the [URL rule](#url-rule); `ConnectorError` (502) when discovery/registration fails |
| `await finish_oauth(state, code)` | `ConnectorInfo` after a check; `ConnectorError` for an unknown, used or expired state, a removed connector, or a failed code exchange (a token endpoint breaking the URL rule included) |

- `owner` is `api.deps.business_owner(key)` (the key id as a string). Every query has `WHERE owner = ?`; another owner's connector behaves as missing.
- `status`: `untested` (never checked), `connected`, `needs_auth` (HTTP 401, or an OAuth connector without usable tokens), `error` (`error` holds a short message, e.g. `The server answered HTTP 404.`, `The server did not answer in time.`, `Cannot connect to the server.`). `tool_count` is 0 unless `connected`.
- Tool names are passed through exactly as the server lists them (`ConnectorTool.name`); calls use the same name. Namespacing for a model (e.g. prefixing the connector) is the caller's job.
- Tool result text: text blocks joined with `\n`; when there is no text, `structured_content` as JSON; other blocks become `[<type> content omitted]`. Cut at `MAX_RESULT_CHARS` = 20 000 characters plus `\n[truncated: N more characters]`. Error results (`is_error`) carry the server's text or `Connector '<name>' failed: <message>` / `Connector '<name>' needs sign-in: <message>` / `Unknown connector '<id>'.`. Tool results are data from a third party, not instructions.
- Timeouts (`business/mcp_client.py`): `TIMEOUT` = 20 s for connect + list tools and for each OAuth HTTP step; `CALL_TIMEOUT` = 60 s for one tool call. Tool listing follows at most `MAX_TOOL_PAGES` = 20 pages.
- Test seams: `hub.http_transport` (an `httpx2` transport, default None) is used for every HTTP request of the hub; the tests set it to `httpx2.ASGITransport(<in-process app>)`. `hub.allow_private_urls` (default False) treats every connector as trusted (see the URL rule); `tests.test_connectors.make_hub` sets it because the in-process server is at `http://127.0.0.1`, except in the URL rule tests.

## URL rule

Who may reach what (`mcp_client.vet_url(url, private_ok)`):

| Connector added with | Schemes | Hosts |
|---|---|---|
| a non-admin key (`trusted = 0`) | `https` only | every address the host resolves to must be public (`ipaddress` `is_global` and not multicast; IPv4-mapped IPv6 and NAT64 (`64:ff9b::/96`, `64:ff9b:1::/48`) checked as the IPv4 address they reach): no loopback, link-local (`169.254.x`, cloud metadata), private (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`), shared (`100.64/10`), unspecified (`0.0.0.0`, `::`) or reserved addresses; a host that does not resolve is refused |
| an admin key (`trusted = 1`) | `http` or `https` | any (local-first: a local n8n, an on-premises server) |

- `add` checks the server URL (`InvalidConnector`, 422, with the reason) and stores `trusted = admin`. Later checks, tool listings and calls run with the stored flag, not the caller's key, and check the URL again before every connection (DNS answers can change); a refusal there gives `status = error` / an error result.
- The OAuth flow runs every URL it fetches through the same rule with the connector's flag: the probe of the server URL, the protected resource metadata URLs (including one named by `WWW-Authenticate`), the authorization server metadata URLs, the registration endpoint, the token endpoint (at start, at the code exchange and at every refresh) and the authorization endpoint.
- Redirects are not followed (httpx2 default; the SDK transports follow only same-origin redirects).
- Limit: the check resolves the host before the HTTP client connects, which resolves it again; a DNS server that answers differently the second time (rebinding) is not caught. stdio connectors are admin-only and have no URL.

## Storage

Tables live in the `database` file given to the hub, created with `CREATE TABLE IF NOT EXISTS` on first use (`business/connectors.py` `SCHEMA`). They do not set `PRAGMA user_version`, so the file can be shared with other stores.

| Table | Columns |
|---|---|
| `connectors` | `id`, `owner`, `listing_id`, `name`, `transport`, `url` (remote), `command` + `args` (JSON, stdio), `auth`, `trusted` (added with an admin key; files without the column get it by `ALTER TABLE` on first use), `secret`, `oauth_client`, `oauth_tokens`, `status`, `error`, `tool_count`, `created_at`, `checked_at` |
| `connector_oauth_states` | `state` (PK), `connector_id` (FK, cascade), `owner`, `flow`, `expires_at` (unix time, `OAUTH_STATE_TTL` = 600 s) |

Encrypted with `Fernet(secrets_key)` (the key configured as `BUSINESS_SECRETS_KEY`; generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`):

- `secret`: the bearer token / API key (`auth=bearer`), or for `auth=oauth` an optional pre-registered OAuth client `client_id:client_secret` (or `client_id`), given as `token` on add.
- `oauth_client`: JSON `mcp_client.OAuthClient`: client id/secret, token endpoint auth method, issuer, authorization and token endpoints, resource (RFC 8707), redirect URI, scope.
- `oauth_tokens`: JSON `{access_token, refresh_token, scope, expires_at}`.
- `connector_oauth_states.flow`: JSON `{client, verifier}` (the PKCE verifier).

Key: `secrets_key` when given (`BUSINESS_SECRETS_KEY`); else, with a `key_file` (the app passes `<business.database folder>/secrets.key`), `local_key` generates one the first time a secret is stored (written to a temporary file, then hard-linked into place, so it appears complete and never replaces a key another process wrote; mode `0600`, which Windows does not enforce) and reads it afterwards, so sign-in and token connectors work without configuration. With neither (a hub built by hand), connectors without secrets still work; adding one with a token or `auth=oauth` raises `InvalidConnector`. Stored secrets read with another key give `status=error`. Secrets never leave the hub: `ConnectorInfo.has_secret` is true when `secret` or `oauth_tokens` is stored; error messages hold no headers or bodies.

## Traces

### Add -> check

`POST /v1/connectors` -> `ConnectorHub.add`:

1. With `listing_id`: `catalog.listing(id)` (unknown -> `InvalidConnector`); `transport`, `url`, `auth` come from the listing unless the request sets them (`request.model_fields_set`). A remote listing with `url=None` and no `url` in the request -> `InvalidConnector` with the listing's description (where to find the URL).
2. `transport == "stdio"` and not `admin` -> `NotAllowed`.
3. `_validate`: stdio needs `command` and `auth=none` without token; remote needs a `url`; `bearer` needs `token`; a token with `auth=none` is refused; a token or `auth=oauth` needs `secrets_key`.
4. Remote: `vet_url(url, admin)` ([URL rule](#url-rule)) -> `InvalidConnector` on refusal.
5. Insert into `connectors` (token encrypted into `secret`, `trusted = admin`), then `check`.

`check` / `tools` -> `_inspect(row)` -> `_run(row, list_tools)`: `_target(row)` checks the URL rule with the stored `trusted` flag and builds `mcp_client.Target(transport, url, command, args, headers)`: `bearer` -> `Authorization: Bearer <secret>`; `oauth` -> `_access_token` (see [Refresh](#refresh)). Then `mcp_client.list_tools(target)` under `anyio.fail_after(TIMEOUT)`: `session()` opens `mcp.Client` over `streamable_http_client(url, http_client=httpx2.AsyncClient(headers))`, `sse_client(url, headers, httpx_client_factory)` or `StdioServerParameters(command, args)`; the client negotiates (`mode="auto"`: `server/discover`, else `initialize`), then `list_tools` page by page. Outcome recorded by `_record`: `connected` + count, `needs_auth` (`AuthRequired`: a 401 seen by the httpx2 response hook, since the SDK reports HTTP errors as a generic MCP error), or `error` + message. `tools` runs `_inspect` for every listed connector concurrently (`asyncio.gather`) and maps each `mcp_types.Tool` to `ConnectorTool`.

### Call

`ConnectorHub.call` -> `_row` (unknown -> error result) -> `_run(row, call_tool)`: `_target` -> `mcp_client.call_tool` under `anyio.fail_after(CALL_TIMEOUT)`: a fresh session, `Client.call_tool(name, arguments)` -> `result_text` -> `truncate` -> `ToolResult(text, result.is_error)`. A tool that raises on the server comes back as `is_error` with the server's message. `AuthRequired` (after the one refresh-and-retry of `_run` for OAuth connectors) records `needs_auth`; other failures return an error result without changing the status.

### Read or write

`ConnectorTool.read_only = bool(tool.annotations and tool.annotations.read_only_hint)`: only tools the server marks with the MCP annotation `readOnlyHint: true` are read-only; a missing annotation or hint counts as a write. Assistants' write policies (`auto` / `ask` / `deny`) act on this flag.

### OAuth: start -> provider -> callback -> finish

The SDK's `OAuthClientProvider` runs the whole authorization inside one HTTP request and awaits the browser there, so it cannot span a web redirect. `mcp_client` runs the same MCP authorization steps split at the redirect, using the SDK's discovery and parsing helpers (`mcp.client.auth.utils`) and models (`OAuthMetadata`, `OAuthToken`, `PKCEParameters`), with httpx2.

1. `POST /v1/connectors/{id}/oauth` -> `start_oauth`: not `auth=oauth` -> `InvalidConnector`. `mcp_client.prepare_oauth(url, redirect_uri, known, preregistered)`:
   - unauthenticated `POST <url>` (JSON-RPC ping); a 401/403 `WWW-Authenticate` may name `resource_metadata` and `scope`;
   - RFC 9728 protected resource metadata (`WWW-Authenticate` URL, then `/.well-known/oauth-protected-resource/<path>`, then the root one) -> authorization server;
   - RFC 8414 metadata (`build_oauth_authorization_server_metadata_discovery_urls`); missing -> `ServerError`; issuer must match;
   - resource = the server URL, or the metadata's `resource` when it covers it; scope from the challenge, else the metadata (`get_client_metadata_scopes`);
   - client: the pre-registered one from `secret` (token endpoint auth `client_secret_basic` unless the server lists only `client_secret_post`; `none` without secret), else the stored `oauth_client` when issuer and redirect URI match, else RFC 7591 registration at `registration_endpoint` (public client, `token_endpoint_auth_method=none`, grants `authorization_code` + `refresh_token`). No registration endpoint and no pre-registered client -> `ServerError` ("enter a pre-registered client as the token").
   Any `ServerError` -> `ConnectorError` (502). Then PKCE (S256) + `state` (`secrets.token_urlsafe(32)`); expired states are deleted and `connector_oauth_states` gets `(state, connector, owner, Fernet{client, verifier}, now + 600)`. Returns `authorize_url` = authorization endpoint + `response_type=code, client_id, redirect_uri, state, code_challenge, code_challenge_method=S256, resource[, scope]`.
2. The browser signs in at the provider, which redirects to `GET /v1/connectors/oauth/callback?state&code` (no API key). `error` or no `code` -> `303 /connectors?oauth_error=<error|no_code>`.
3. `finish_oauth(state, code)`: `_take_state` reads and deletes the state row in one statement (`DELETE ... RETURNING *`; SQLite older than 3.35: `BEGIN IMMEDIATE`, select, delete), so a state is used at most once even under concurrent callbacks; missing or past `expires_at` -> `ConnectorError` (callback -> `303 /connectors?oauth_error=expired`). A callback with `error=` does not consume the row; it expires. `mcp_client.exchange_code` posts `grant_type=authorization_code, code, redirect_uri, code_verifier, client_id, resource` (+ client secret as Basic or form field) to the token endpoint; non-2xx -> `ConnectorError`. `_save_sign_in` stores `oauth_client` and `oauth_tokens` (`expires_at = now + expires_in`), then `check` -> `303 /connectors?connected=<id>`.
4. Later operations use the access token, renewed as below.

### Refresh

`_access_token(row, stale=None)`:

1. No stored tokens -> `AuthRequired` ("Not signed in yet").
2. Without `stale`: the stored token is used while `expires_at` is unknown (no `expires_in` in the token response) or more than `REFRESH_MARGIN` = 60 s away.
3. Otherwise, under the connector's `asyncio.Lock` (`_refresh_locks[connector id]`, per process): the row is read again; if another operation renewed the token meanwhile (not expiring, or different from `stale`) that token is used. Else no refresh token -> `AuthRequired` ("sign in again"); else `mcp_client.refresh` posts `grant_type=refresh_token` (a response without a new refresh token keeps the old one), `_save_sign_in` stores the result. A failed refresh -> `AuthRequired`. So concurrent operations spend a rotating refresh token once.
4. `_run`: when the server answers 401 to an OAuth connector's request, the refused token is passed as `stale` (one refresh, step 3) and the operation is retried once; this also covers tokens issued without `expires_in`. A second 401, or a refresh that fails, records `needs_auth`: start the sign-in again. A 401 means the request was not served, so retrying a tool call does not run it twice.

Providers without dynamic client registration (marked in the catalog descriptions): create an OAuth client at the provider with redirect URL `<public_url>/v1/connectors/oauth/callback`, then add the connector with `auth: "oauth"` and `token: "client_id:client_secret"`.

### stdio

`transport: "stdio"` starts `command args...` as a subprocess of the API server (SDK `stdio_client`, environment limited to the SDK's `get_default_environment()`) for each operation and talks MCP over its stdin/stdout. It runs with the server's permissions, so only admin keys may add one (`NotAllowed` otherwise). stdio connectors take no token (`auth=none`); a server that needs credentials must read them from its own configuration.

Remote connectors make the API server send HTTP requests to the URL the owner gives, within the [URL rule](#url-rule).

## Built-in apps

A listing with `builtin: true` runs in this process. `add` with its `listing_id` stores a row with `transport = "builtin"` (`_add_builtin`: a URL, command, token or sign-in is refused; `transport: "builtin"` without such a listing too); `check`, `tools` and `call` go to the app instead of an MCP session; no network, no secret. One exists: `workspace-database` ([business/database.py](../business/database.py), README "Workspace databases"), which may be added several times (one SQLite file each, `<database folder>/databases/<connector id>.db`). Its eight tools carry `read_only` themselves (`list_tables`, `describe_table`, `query`), so assistants' write policies apply to the rest.

## Store catalog

`business/catalog.py` `LISTINGS`. Each listing has a `tagline` (the store card), a `description` (setup text of the add dialog), a `category` and optional `also_in` categories. Transport: every remote listing is `streamable_http`. Where the publisher's page does not name the transport, it documents a remote HTTP endpoint (client configs with `"type": "http"` or a plain `url`, or JSON-RPC over HTTP POST), which is what MCP's Streamable HTTP transport is; Slack's page states that SSE is not supported. Auth is what this app uses by default; alternatives are in the description.

| id | Publisher | URL, or how to find it | Auth | Featured | Source |
|---|---|---|---|---|---|
| `workspace-database` | Built in | none (built-in app) | none | (own section) | [business/database.py](../business/database.py) |
| `google-drive`, `google-docs`, `google-sheets`, `gmail`, `google-calendar` | Google | `https://drivemcp.googleapis.com/mcp/v1`, `docsmcp`, `sheetsmcp`, `gmailmcp`, `calendarmcp` (same pattern). Developer Preview Program members; OAuth client required | oauth (pre-registered client) | Drive, Docs | [Configure the Google Workspace MCP servers](https://developers.google.com/workspace/guides/configure-mcp-servers) |
| `google-workspace` | Google | The other products, one server each: `https://<product>mcp.googleapis.com/mcp/v1` (Slides `slidesmcp`, Chat `chatmcp`, Classroom `classroommcp`); Contacts `https://people.googleapis.com/mcp/v1`. Developer Preview Program members; OAuth client required | oauth (pre-registered client) | | same page |
| `dropbox` | Dropbox | `https://mcp.dropbox.com/mcp` (open beta; the Dash server at `/dash` is a different product) | oauth | yes | [How to connect the Dropbox remote MCP server](https://help.dropbox.com/integrations/connect-dropbox-mcp-server) |
| `box` | Box | `https://mcp.box.com` (enabled by a Box admin under Admin Console > Integrations > Box MCP Server, which shows the OAuth client ID and secret) | oauth (pre-registered client) | | [Box MCP server (remote)](https://developer.box.com/guides/box-mcp/remote) |
| `google-ads` | Google | Your own Cloud Run deployment (URL ends in `/mcp`), or local stdio `pipx run --spec git+https://github.com/googleads/google-ads-mcp.git google-ads-mcp`. Read-only | oauth (pre-registered client) | | [Google Ads MCP server](https://developers.google.com/google-ads/api/docs/developer-toolkit/mcp-server) |
| `microsoft-365` | Microsoft | `https://workiq.svc.cloud.microsoft/mcp` (Work IQ MCP; Entra ID, discovered via `/.well-known/oauth-protected-resource`) | oauth | yes | [Work IQ MCP overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview), [GitHub Copilot CLI quickstart](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/github-copilot-cli), [tooling servers overview](https://learn.microsoft.com/microsoft-agent-365/tooling-servers-overview) |
| `hubspot` | HubSpot | `https://mcp.hubspot.com` (MCP auth app: client ID + secret, PKCE) | oauth (pre-registered client) | yes | [Integrate with the remote HubSpot MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server) |
| `salesforce` | Salesforce | Per org: the hosted MCP server configured by an admin; the URL comes from that configuration. External Client App consumer key | oauth (pre-registered client) | | [Connecting an MCP Client](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/client-connection-overview.html) |
| `gohighlevel` | HighLevel | `https://services.leadconnectorhq.com/mcp/openai/v2/` (the docs list one URL per client: `/mcp/anthropic/v2`, `/mcp/openai/v2/`, `/mcp/cursor/v2`, `/mcp/muse/v2/`) | oauth | | [HighLevel MCP Server](https://marketplace.gohighlevel.com/docs/other/mcp) |
| `snowflake` | Snowflake | `https://<account_url>/api/v2/databases/{database}/schemas/{schema}/mcp-servers/{name}`; no dynamic registration | oauth (pre-registered client) | | [Snowflake-managed MCP server](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp) |
| `stripe` | Stripe | `https://mcp.stripe.com`; alternative: `auth: "bearer"` with an agent API key | oauth | yes | [Stripe MCP](https://docs.stripe.com/mcp) |
| `square` | Square | `https://mcp.squareup.com/mcp` (beta, production only, client allowlist) | oauth | | [Square MCP server](https://developer.squareup.com/docs/mcp) |
| `slack` | Slack | `https://mcp.slack.com/mcp` (no SSE, no dynamic registration; registered Slack app, confidential OAuth) | oauth (pre-registered client) | yes | [Slack MCP server](https://docs.slack.dev/ai/slack-mcp-server) |
| `notion` | Notion | `https://mcp.notion.com/mcp`; alternative: `auth: "bearer"` with an MCP token (Business/Enterprise) | oauth | yes | [Get started with Notion MCP](https://developers.notion.com/guides/mcp/get-started-with-mcp) |
| `atlassian` | Atlassian | `https://mcp.atlassian.com/v2/mcp` (Jira, Confluence, Bitbucket, JSM, Loom) | oauth | | [Getting started with the Atlassian Rovo MCP Server](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/) |
| `github` | GitHub | `https://api.githubcopilot.com/mcp/` with a personal access token; local: Docker `ghcr.io/github/github-mcp-server` (stdio) | bearer | | [github/github-mcp-server](https://github.com/github/github-mcp-server) |
| `n8n` | n8n | `https://<your-n8n-domain>/mcp-server/http`, from Settings > Instance-level MCP > Connect a client; token generated there | bearer | | [Connect to the n8n MCP server](https://docs.n8n.io/connect/connect-to-n8n-mcp-server) |
| `supabase` | Supabase | `https://mcp.supabase.com/mcp`, optionally `?project_ref=<ref>&read_only=true&features=...` | oauth | | [supabase/mcp](https://github.com/supabase/mcp) |
| `databricks` | Databricks | `https://<workspace-hostname>/api/2.0/mcp/sql`, `/api/2.0/mcp/genie/{genie_space_id}`, `/api/2.0/mcp/ai-search/{catalog}/{schema}/{index_name}`, `/api/2.0/mcp/functions/{catalog}/{schema}/{function_name}` (public preview) | oauth (pre-registered client) | | [Databricks managed MCP servers](https://docs.databricks.com/aws/generative-ai/mcp/managed-mcp), [authentication](https://docs.databricks.com/aws/en/agents/mcp-tools/authentication-networking) |
| `shopify-catalog` | Shopify | `https://catalog.shopify.com/api/ucp/mcp` (Global Catalog MCP; requests must carry a `meta.ucp-agent.profile` URL, which this client does not send) | none | | [Global Catalog MCP](https://shopify.dev/docs/agents/catalog/global-catalog) |

"pre-registered client": the publisher's page requires an OAuth client created with the provider (or states that dynamic client registration is unsupported); give it as `token: "client_id:client_secret"`. The other OAuth listings are tried with dynamic registration first; if the provider's metadata has no `registration_endpoint`, `start_oauth` says so and the same pre-registered route applies.

Not verified from this environment: the servers themselves (the sandbox proxy refuses those hosts); the catalog follows the publishers' pages as read on 2026-11-02. The Dropbox and Box rows were added on 2026-11-15 from search results quoting those pages (the pages themselves were not opened), and the per-product Google rows reuse the URLs of the Google page above: check each against its page before relying on it.

### Recipe: add a store listing

1. Read the publisher's MCP page: server URL (or the URL pattern and where the customer finds it), transport, auth (OAuth with or without dynamic registration, bearer token/API key, none), availability wording.
2. Append a `ConnectorListing` to `LISTINGS` in `business/catalog.py`: unique kebab-case `id`; a one-line `tagline`; `category` (and `also_in` for further ones); `url=None` when it depends on the account, with the description saying how to find it (append `_NO_DCR` when the provider needs a pre-registered OAuth client); `docs_url` = the page you read; `featured=True` only for general business tools (keep 6-8 featured).
3. Add the id to `test_catalog_integrity` and a row to the table above with the source link.
