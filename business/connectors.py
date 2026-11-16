"""business/connectors.py

`ConnectorHub`: the owner's connectors. Installs (store listing or by hand), secrets encrypted at rest,
connection checks, tool discovery and tool calls through the official `mcp` SDK, and the OAuth flow for remote
servers that need it. The network side is `business.mcp_client`; the store listings are `business.catalog`.

Built-in apps (`transport = "builtin"`, added from a `builtin` listing) run in this process instead of on an MCP
server: the hub lists and calls their tools through `business.database.DatabaseApp` (one SQLite file per
installed connector, deleted with it). They need no URL, sign-in or secret.

    hub = ConnectorHub(database, secrets_key, public_url)
    info = await hub.add(owner, ConnectorCreate(listing_id="stripe", name="Stripe"), admin=False)
    start = await hub.start_oauth(owner, info.id)      # browser -> start.authorize_url -> provider
    info = await hub.finish_oauth(state, code)         # the provider's redirect (/v1/connectors/oauth/callback)
    tools = await hub.tools(owner, [info.id])          # ConnectorTool.read_only <- MCP readOnlyHint
    result = await hub.call(owner, info.id, "stripe_api_read", {...})   # ToolResult, never raises

Tables (in `database`, next to whatever else lives there; `CREATE ... IF NOT EXISTS`, no PRAGMA user_version):

    connectors              one row per installed connector, scoped by `owner` (the API key id). `secret`,
                            `oauth_client` and `oauth_tokens` are Fernet tokens (key: `secrets_key`).
    connector_oauth_states  pending sign-ins: state -> connector, owner, encrypted {client, PKCE verifier},
                            expiry (`OAUTH_STATE_TTL`). One use: `finish_oauth` deletes the row it reads.

A connection is opened per operation (check, tools, call) and every network call is bounded by a timeout.
Secrets are never returned (`ConnectorInfo.has_secret` only says one is stored) and never logged.

URLs: a connector added with a non-admin key (`trusted = 0`) may reach only https URLs on public addresses, and
so may every URL its OAuth flow fetches (`mcp_client.vet_url`); admin keys may use http and local or private
networks. The rule is checked on add (`InvalidConnector`) and again before every connection (DNS may change).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from cryptography.fernet import Fernet, InvalidToken
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.shared.auth import OAuthToken

from business import catalog
from business.database import DatabaseApp, DatabaseError
from business.mcp_client import (
    AuthRequired,
    OAuthClient,
    ServerError,
    Target,
    UnsafeUrl,
    authorize_url,
    call_tool,
    exchange_code,
    list_tools,
    prepare_oauth,
    refresh,
    vet_url,
)
from business.schema import ConnectorCreate, ConnectorInfo, ConnectorListing, ConnectorTool, OAuthStart

CALLBACK_PATH = "/v1/connectors/oauth/callback"
BUILTIN = "builtin"
DATABASE_LISTING = "workspace-database"
OAUTH_STATE_TTL = 600  # seconds a started sign-in stays valid
REFRESH_MARGIN = 60  # seconds before expiry an access token is renewed

SCHEMA = """
CREATE TABLE IF NOT EXISTS connectors (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    listing_id TEXT,
    name TEXT NOT NULL,
    transport TEXT NOT NULL,  -- streamable_http | sse | stdio | builtin
    url TEXT,
    command TEXT,
    args TEXT NOT NULL DEFAULT '[]',  -- JSON list
    auth TEXT NOT NULL,  -- none | bearer | oauth
    trusted INTEGER NOT NULL DEFAULT 0,  -- added with an admin key: http and private networks allowed
    secret BLOB,  -- Fernet: bearer token, or (oauth) a pre-registered client "client_id[:client_secret]"
    oauth_client BLOB,  -- Fernet: JSON mcp_client.OAuthClient (registration and endpoints)
    oauth_tokens BLOB,  -- Fernet: JSON {access_token, refresh_token, scope, expires_at}
    status TEXT NOT NULL DEFAULT 'untested',  -- untested | connected | needs_auth | error
    error TEXT,
    tool_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_connectors_owner ON connectors(owner, created_at);

CREATE TABLE IF NOT EXISTS connector_oauth_states (
    state TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    flow BLOB NOT NULL,  -- Fernet: JSON {client: OAuthClient, verifier}
    expires_at REAL NOT NULL
);
"""


class ConnectorError(RuntimeError):
    """A connector could not be reached, refused the credentials, or failed a call."""


class InvalidConnector(ValueError):
    """A connector request that cannot work (e.g. a remote transport without a URL, a secret without a key)."""


class NotAllowed(PermissionError):
    """The caller may not do this (e.g. a stdio connector added with a non-admin key)."""


@dataclass
class ToolResult:
    text: str
    is_error: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def local_key(path: Path) -> bytes:
    """The Fernet key kept in `path`, generated on first use (owner-only file). For installs that set no
    `BUSINESS_SECRETS_KEY`: tokens are still encrypted at rest, with a key that lives beside the database."""
    try:
        return path.read_bytes().strip()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with os.fdopen(os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
        file.write(Fernet.generate_key())
    try:
        os.link(draft, path)  # appears complete or not at all, and never replaces a key another process wrote
    except FileExistsError:
        pass
    finally:
        draft.unlink()
    return path.read_bytes().strip()


def _info(row: sqlite3.Row) -> ConnectorInfo:
    return ConnectorInfo(
        id=row["id"], listing_id=row["listing_id"], name=row["name"], transport=row["transport"], url=row["url"],
        command=row["command"], args=json.loads(row["args"]), auth=row["auth"],
        has_secret=row["secret"] is not None or row["oauth_tokens"] is not None, status=row["status"],
        error=row["error"], tool_count=row["tool_count"], created_at=row["created_at"], checked_at=row["checked_at"])


class ConnectorHub:
    http_transport: httpx2.AsyncBaseTransport | None = None  # tests: an ASGI transport to in-process servers
    allow_private_urls = False  # True: every connector is treated as trusted (tests reaching 127.0.0.1)

    def __init__(self, database: Path, secrets_key: bytes | None, public_url: str, key_file: Path | None = None):
        """`secrets_key`: Fernet key for tokens at rest. Without one, `key_file` names a file holding a key
        generated on first need (`local_key`); with neither, connectors with secrets cannot be added.
        `public_url`: where the API is reached from the browser, for the OAuth redirect."""
        self.path = Path(database)
        self._fernet = Fernet(secrets_key) if secrets_key else None
        self._key_file = key_file
        self.databases = DatabaseApp(self.path.parent / "databases")
        self.redirect_uri = public_url.rstrip("/") + CALLBACK_PATH
        self._ready = False
        self._lock = threading.Lock()
        self._refresh_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)  # per connector id

    @property
    def fernet(self) -> Fernet | None:
        """The cipher for stored secrets; a `key_file` key is created the first time one is needed."""
        if self._fernet is None and self._key_file is not None:
            self._fernet = Fernet(local_key(self._key_file))
        return self._fernet

    # --- store -------------------------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection per operation, committed on success; the tables are created on first use."""
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.path) as conn:
                    conn.executescript(SCHEMA)
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(connectors)")}
                    if "trusted" not in columns:  # files created before the column existed
                        conn.execute("ALTER TABLE connectors ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0")
                self._ready = True
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _row(self, owner: str, connector_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM connectors WHERE owner = ? AND id = ?",
                                (owner, connector_id)).fetchone()

    def _record(self, row: sqlite3.Row, status: str, error: str | None, tool_count: int = 0) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE connectors SET status = ?, error = ?, tool_count = ?, checked_at = ?"
                         " WHERE owner = ? AND id = ?", (status, error, tool_count, _now(), row["owner"], row["id"]))

    def _encrypt(self, value: str) -> bytes:
        return self.fernet.encrypt(value.encode())

    def _decrypt(self, value: bytes) -> str:
        if self.fernet is None:
            raise ServerError("BUSINESS_SECRETS_KEY is not set, so the stored credentials cannot be read.")
        try:
            return self.fernet.decrypt(value).decode()
        except InvalidToken as exc:
            raise ServerError("The stored credentials cannot be decrypted (BUSINESS_SECRETS_KEY changed?).") from exc

    # --- installed connectors ---------------------------------------------------------------------

    def catalog(self) -> list[ConnectorListing]:
        """The store: built-in apps, then featured listings, then the rest."""
        return catalog.catalog()

    def list(self, owner: str) -> list[ConnectorInfo]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM connectors WHERE owner = ? ORDER BY created_at", (owner,)).fetchall()
        return [_info(row) for row in rows]

    def get(self, owner: str, connector_id: str) -> ConnectorInfo | None:
        row = self._row(owner, connector_id)
        return _info(row) if row else None

    async def add(self, owner: str, request: ConnectorCreate, admin: bool) -> ConnectorInfo:
        """Store it, then check it. `NotAllowed` (403) for stdio unless `admin`; `InvalidConnector` (422)."""
        given = request.model_fields_set
        transport, url, auth = request.transport, request.url, request.auth
        if request.listing_id is not None:
            listing = catalog.listing(request.listing_id)
            if listing is None:
                raise InvalidConnector(f"Unknown store listing '{request.listing_id}'.")
            if listing.builtin:
                return await self._add_builtin(owner, request)
            transport = request.transport if "transport" in given else listing.transport
            url = request.url if "url" in given else listing.url
            auth = request.auth if "auth" in given else listing.auth
            if transport != "stdio" and not url:
                raise InvalidConnector(f"{listing.name} has no fixed server URL; give `url`. {listing.description}")
        if transport == BUILTIN:
            raise InvalidConnector("Built-in apps are added from their store listing.")
        if transport == "stdio" and not admin:
            raise NotAllowed("stdio connectors run a command on the server: admin keys only.")
        self._validate(transport, url, request.command, auth, request.token)
        if transport != "stdio":
            try:
                await vet_url(url, admin or self.allow_private_urls)
            except UnsafeUrl as exc:
                raise InvalidConnector(str(exc)) from exc
        connector_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO connectors (id, owner, listing_id, name, transport, url, command, args, auth, trusted,"
                " secret, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (connector_id, owner, request.listing_id, request.name, transport,
                 url if transport != "stdio" else None, request.command if transport == "stdio" else None,
                 json.dumps(request.args if transport == "stdio" else []), auth, int(admin),
                 self._encrypt(request.token) if request.token else None, _now()))
        return await self.check(owner, connector_id)

    async def _add_builtin(self, owner: str, request: ConnectorCreate) -> ConnectorInfo:
        """A built-in app: nothing to connect to, so no URL, command, sign-in or token."""
        if request.url or request.command or request.token or request.auth != "none":
            raise InvalidConnector("Built-in apps take no URL, command, sign-in or token.")
        connector_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute("INSERT INTO connectors (id, owner, listing_id, name, transport, auth, trusted, created_at)"
                         " VALUES (?, ?, ?, ?, ?, 'none', 0, ?)",
                         (connector_id, owner, request.listing_id, request.name, BUILTIN, _now()))
        return await self.check(owner, connector_id)

    def _validate(self, transport: str, url: str | None, command: str | None, auth: str, token: str | None) -> None:
        if transport == "stdio":
            if not command:
                raise InvalidConnector("A stdio connector needs `command`.")
            if auth != "none" or token:
                raise InvalidConnector("stdio connectors take no token or sign-in (auth must be 'none').")
            return
        if not url:
            raise InvalidConnector("A remote connector needs a `url`.")
        if auth == "bearer" and not token:
            raise InvalidConnector("Bearer auth needs `token` (the token or API key).")
        if auth == "none" and token:
            raise InvalidConnector("A token needs auth 'bearer' (or 'oauth' for a pre-registered OAuth client).")
        if (token or auth == "oauth") and self.fernet is None:
            raise InvalidConnector("Set BUSINESS_SECRETS_KEY to store tokens and sign-ins.")

    def remove(self, owner: str, connector_id: str) -> bool:
        """Remove a connector with its stored secrets; a database app's data file is deleted with it."""
        row = self._row(owner, connector_id)
        with self._connect() as conn:
            removed = conn.execute("DELETE FROM connectors WHERE owner = ? AND id = ?",
                                   (owner, connector_id)).rowcount > 0
        if removed:
            self._refresh_locks.pop(connector_id, None)
            if row["transport"] == BUILTIN:
                self.databases.remove(connector_id)
        return removed

    def database(self, owner: str, connector_id: str) -> DatabaseApp | None:
        """The database app, when `connector_id` is one of the owner's workspace databases; else None."""
        row = self._row(owner, connector_id)
        is_database = row is not None and row["transport"] == BUILTIN and row["listing_id"] == DATABASE_LISTING
        return self.databases if is_database else None

    def _trusted(self, row: sqlite3.Row) -> bool:
        return bool(row["trusted"]) or self.allow_private_urls

    # --- tools -----------------------------------------------------------------------------------------

    async def check(self, owner: str, connector_id: str) -> ConnectorInfo | None:
        """Connect, list the tools, record status and tool count."""
        row = self._row(owner, connector_id)
        if row is None:
            return None
        await self._inspect(row)
        return self.get(owner, connector_id)

    async def tools(self, owner: str, connector_ids: list[str]) -> list[ConnectorTool]:
        """Tools of the given connectors that are connected; unknown or failing connectors are skipped."""
        rows = [row for cid in dict.fromkeys(connector_ids) if (row := self._row(owner, cid))]
        listed = await asyncio.gather(*(self._inspect(row) for row in rows))
        return [tool for tools in listed for tool in tools or []]

    async def _inspect(self, row: sqlite3.Row) -> list[ConnectorTool] | None:
        """List the tools of one connector and record the outcome; None when it is not connected."""
        try:
            tools = await self._list_tools(row)
        except AuthRequired as exc:
            self._record(row, "needs_auth", str(exc))
            return None
        except ServerError as exc:
            self._record(row, "error", str(exc))
            return None
        self._record(row, "connected", None, len(tools))
        return tools

    async def _list_tools(self, row: sqlite3.Row) -> list[ConnectorTool]:
        if row["transport"] == BUILTIN:
            return self.databases.tools(row["id"])
        listed = await self._run(row, lambda target: list_tools(target, self.http_transport))
        return [ConnectorTool(connector_id=row["id"], name=tool.name, description=tool.description or "",
                              read_only=bool(tool.annotations and tool.annotations.read_only_hint),
                              input_schema=tool.input_schema) for tool in listed]

    async def call(self, owner: str, connector_id: str, tool: str, arguments: dict) -> ToolResult:
        """Run one tool. Never raises for tool or connection errors: they come back as `is_error`."""
        row = self._row(owner, connector_id)
        if row is None:
            return ToolResult(f"Unknown connector '{connector_id}'.", is_error=True)
        if row["transport"] == BUILTIN:
            return await self._call_builtin(row, tool, arguments)
        try:
            result = await self._run(row, lambda target: call_tool(target, tool, arguments, self.http_transport))
        except AuthRequired as exc:
            self._record(row, "needs_auth", str(exc))
            return ToolResult(f"Connector '{row['name']}' needs sign-in: {exc}", is_error=True)
        except ServerError as exc:
            return ToolResult(f"Connector '{row['name']}' failed: {exc}", is_error=True)
        return ToolResult(result.text, result.is_error)

    async def _call_builtin(self, row: sqlite3.Row, tool: str, arguments: dict) -> ToolResult:
        try:
            return ToolResult(await asyncio.to_thread(self.databases.call, row["id"], tool, arguments or {}))
        except DatabaseError as exc:
            return ToolResult(str(exc), is_error=True)
        except KeyError:
            return ToolResult(f"Connector '{row['name']}' has no tool '{tool}'.", is_error=True)

    async def _run[T](self, row: sqlite3.Row, operation: Callable[[Target], Awaitable[T]]) -> T:
        """`operation` on the connector's target. An OAuth connector answered with 401 gets one token refresh and
        one retry (a 401 means the request was not served, so retrying a tool call is safe)."""
        target = await self._target(row)
        try:
            return await operation(target)
        except AuthRequired:
            if row["auth"] != "oauth":
                raise
            stale = target.headers["Authorization"].removeprefix("Bearer ")
            return await operation(await self._target(row, stale))

    async def _target(self, row: sqlite3.Row, stale: str | None = None) -> Target:
        """Where and how to connect, with the credentials as headers. `ServerError` when the URL breaks the URL
        rule; `AuthRequired` without usable OAuth tokens."""
        if row["transport"] != "stdio":
            await vet_url(row["url"], self._trusted(row))
        headers = {}
        if row["auth"] == "bearer":
            headers["Authorization"] = f"Bearer {self._decrypt(row['secret'])}"
        elif row["auth"] == "oauth":
            headers["Authorization"] = f"Bearer {await self._access_token(row, stale)}"
        return Target(row["transport"], row["url"], row["command"], json.loads(row["args"]), headers)

    # --- OAuth ---------------------------------------------------------------------------------------------

    def _tokens(self, row: sqlite3.Row | None) -> dict:
        if row is None or row["oauth_tokens"] is None or row["oauth_client"] is None:
            raise AuthRequired("Not signed in yet: start the OAuth sign-in.")
        return json.loads(self._decrypt(row["oauth_tokens"]))

    @staticmethod
    def _usable(tokens: dict, stale: str | None) -> bool:
        if stale is not None:  # the server refused `stale`: usable only if another operation already renewed it
            return tokens["access_token"] != stale
        return tokens["expires_at"] is None or time.time() < tokens["expires_at"] - REFRESH_MARGIN

    async def _access_token(self, row: sqlite3.Row, stale: str | None = None) -> str:
        """The stored access token, renewed with the refresh token when it is about to expire or when the server
        refused `stale`. Renewals of one connector run one at a time and re-read the row, so concurrent
        operations do not spend a rotating refresh token twice."""
        tokens = self._tokens(row)
        if self._usable(tokens, stale):
            return tokens["access_token"]
        async with self._refresh_locks[row["id"]]:
            row = self._row(row["owner"], row["id"])
            tokens = self._tokens(row)
            if self._usable(tokens, stale):
                return tokens["access_token"]
            if not tokens.get("refresh_token"):
                raise AuthRequired("The sign-in expired: sign in again.")
            client = OAuthClient.from_json(self._decrypt(row["oauth_client"]))
            try:
                token = await refresh(client, tokens["refresh_token"], self._trusted(row), self.http_transport)
            except ServerError as exc:
                raise AuthRequired(f"The sign-in expired and could not be renewed ({exc}); sign in again.") from exc
            self._save_sign_in(row["owner"], row["id"], client, token)
            return token.access_token

    def _save_sign_in(self, owner: str, connector_id: str, client: OAuthClient, token: OAuthToken) -> None:
        tokens = {"access_token": token.access_token, "refresh_token": token.refresh_token, "scope": token.scope,
                  "expires_at": time.time() + token.expires_in if token.expires_in is not None else None}
        with self._connect() as conn:
            conn.execute("UPDATE connectors SET oauth_client = ?, oauth_tokens = ? WHERE owner = ? AND id = ?",
                         (self._encrypt(client.to_json()), self._encrypt(json.dumps(tokens)), owner, connector_id))

    async def start_oauth(self, owner: str, connector_id: str) -> OAuthStart | None:
        row = self._row(owner, connector_id)
        if row is None:
            return None
        if row["auth"] != "oauth":
            raise InvalidConnector("This connector does not use OAuth sign-in.")
        if self.fernet is None:
            raise InvalidConnector("Set BUSINESS_SECRETS_KEY to store sign-ins.")
        try:
            preregistered = None
            if row["secret"] is not None:
                client_id, _, client_secret = self._decrypt(row["secret"]).partition(":")
                preregistered = (client_id, client_secret or None)
            known = OAuthClient.from_json(self._decrypt(row["oauth_client"])) if row["oauth_client"] else None
            client = await prepare_oauth(row["url"], self.redirect_uri, self._trusted(row), known, preregistered,
                                         self.http_transport)
        except UnsafeUrl as exc:
            raise InvalidConnector(str(exc)) from exc
        except ServerError as exc:
            raise ConnectorError(str(exc)) from exc
        pkce, state = PKCEParameters.generate(), secrets.token_urlsafe(32)
        flow = json.dumps({"client": json.loads(client.to_json()), "verifier": pkce.code_verifier})
        with self._connect() as conn:
            conn.execute("DELETE FROM connector_oauth_states WHERE expires_at < ?", (time.time(),))
            conn.execute("INSERT INTO connector_oauth_states VALUES (?, ?, ?, ?, ?)",
                         (state, connector_id, owner, self._encrypt(flow), time.time() + OAUTH_STATE_TTL))
        return OAuthStart(authorize_url=authorize_url(client, state, pkce.code_challenge))

    async def finish_oauth(self, state: str, code: str) -> ConnectorInfo:
        """Called by the provider's redirect. `ConnectorError` for an unknown or expired `state`."""
        pending = self._take_state(state)
        if pending is None or pending["expires_at"] < time.time():
            raise ConnectorError("Unknown or expired sign-in; start it again.")
        owner, connector_id = pending["owner"], pending["connector_id"]
        row = self._row(owner, connector_id)
        if row is None:
            raise ConnectorError("The connector was removed during sign-in.")
        try:
            flow = json.loads(self._decrypt(pending["flow"]))
            client = OAuthClient(**flow["client"])
            token = await exchange_code(client, code, flow["verifier"], self._trusted(row), self.http_transport)
        except ServerError as exc:
            raise ConnectorError(str(exc)) from exc
        self._save_sign_in(owner, connector_id, client, token)
        info = await self.check(owner, connector_id)
        if info is None:
            raise ConnectorError("The connector was removed during sign-in.")
        return info

    def _take_state(self, state: str) -> sqlite3.Row | None:
        """Read and delete a pending sign-in in one step, so a state is used at most once."""
        with self._connect() as conn:
            if sqlite3.sqlite_version_info >= (3, 35):
                return conn.execute("DELETE FROM connector_oauth_states WHERE state = ? RETURNING *",
                                    (state,)).fetchone()
            conn.execute("BEGIN IMMEDIATE")  # older SQLite: no RETURNING; the write lock makes read+delete atomic
            pending = conn.execute("SELECT * FROM connector_oauth_states WHERE state = ?", (state,)).fetchone()
            conn.execute("DELETE FROM connector_oauth_states WHERE state = ?", (state,))
            return pending
