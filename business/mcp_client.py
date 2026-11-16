"""business/mcp_client.py

The network side of connectors, on the official `mcp` SDK (2.x; it speaks HTTP through `httpx2`):

    tools = await list_tools(target)                      # list[mcp_types.Tool]
    result = await call_tool(target, "search", {"q": "x"})  # ToolText(text, is_error)

and the steps of the MCP authorization flow (RFC 9728 protected resource metadata -> RFC 8414 authorization
server metadata -> RFC 7591 dynamic registration -> authorization code with PKCE -> refresh), built from the
SDK's discovery and parsing helpers. The SDK's own `OAuthClientProvider` runs the whole flow inside one HTTP
request and waits there for the browser, so it cannot span a web redirect; these functions split it at the
redirect so the state can live in the store:

    client = await prepare_oauth(server_url, redirect_uri)   # discover + register -> OAuthClient
    url = authorize_url(client, state, pkce.code_challenge)  # the browser goes there
    tokens = await exchange_code(client, code, pkce.code_verifier)
    tokens = await refresh(client, tokens.refresh_token)

Every call is bounded (`TIMEOUT`, `CALL_TIMEOUT`). Failures raise `ServerError` with a short, secret-free
message, or `AuthRequired` when the server answered 401. `transport`: an httpx2 transport for tests (ASGI).

URL rule (`vet_url`, applied by the hub to the server URL and here to every URL the OAuth steps fetch):
`private_ok=False` (connectors added with a non-admin key) allows only https to hosts whose every address is
public (not loopback, link-local, private, shared, unspecified, reserved or multicast); a host that does not
resolve is refused. `private_ok=True` (admin keys) allows http and any address. Redirects are not followed.
"""

from __future__ import annotations

import base64
import ipaddress
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from urllib.parse import quote, urlencode, urlparse

import anyio
import httpx2
from mcp import Client, MCPError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_registration_request,
    create_oauth_metadata_request,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    handle_registration_response,
    handle_token_response_scopes,
    issuers_match,
)
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata, OAuthToken
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from mcp_types import CallToolResult, Implementation, Tool

TIMEOUT = 20.0  # seconds for connecting and listing tools, and for each OAuth step
CALL_TIMEOUT = 60.0  # seconds for one tool call
MAX_RESULT_CHARS = 20_000  # tool result text beyond this is cut, with a note
MAX_TOOL_PAGES = 20
CLIENT_INFO = Implementation(name="tax-doc-api-business", version="1")


class ServerError(Exception):
    """The server could not be reached, failed, or refused; the message is short and holds no secret."""


class AuthRequired(ServerError):
    """The server answered 401, or the connector has no usable OAuth tokens."""


class UnsafeUrl(ServerError):
    """A URL this key may not reach (see the URL rule above)."""


async def vet_url(url: str, private_ok: bool) -> None:
    """`UnsafeUrl` unless `url` is http(s) and allowed by the URL rule. Resolves the host (bounded)."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeUrl("The URL must be an http(s) URL with a host.")
    if private_ok:
        return
    if parts.scheme != "https":
        raise UnsafeUrl("Only https URLs are allowed (admin keys may also use http).")
    for address in await _addresses(parts.hostname):
        address = getattr(address, "ipv4_mapped", None) or _nat64(address) or address
        if not address.is_global or address.is_multicast:
            raise UnsafeUrl(f"{parts.hostname} is a local or private address ({address}); only admin keys may "
                            "connect to local or private networks.")


NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def _nat64(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address a NAT64 address (RFC 6052 / 8215) reaches: the URL rule judges that one."""
    if address.version == 6 and any(address in net for net in NAT64):
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


async def _addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        with anyio.fail_after(TIMEOUT):
            infos = await anyio.getaddrinfo(host, None)
    except (OSError, TimeoutError) as exc:
        raise UnsafeUrl(f"Cannot resolve {host}.") from exc
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


@dataclass
class Target:
    """How to reach one server. `headers` carry the credentials (never logged)."""

    transport: str  # streamable_http | sse | stdio
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolText:
    text: str
    is_error: bool


# --- sessions -------------------------------------------------------------------------------------------


def http_client(transport: httpx2.AsyncBaseTransport | None = None, headers: dict | None = None,
                statuses: list[int] | None = None, timeout: float | httpx2.Timeout = TIMEOUT,
                auth: httpx2.Auth | None = None) -> httpx2.AsyncClient:
    """An httpx2 client; `statuses` collects every response status (the SDK turns HTTP errors into a generic
    MCP error, so this is how a 401 is told apart)."""
    async def record(response: httpx2.Response) -> None:
        statuses.append(response.status_code)

    return httpx2.AsyncClient(transport=transport, headers=headers, auth=auth,
                              timeout=timeout if isinstance(timeout, httpx2.Timeout) else httpx2.Timeout(timeout),
                              event_hooks={"response": [record]} if statuses is not None else None)


@asynccontextmanager
async def session(target: Target, transport: httpx2.AsyncBaseTransport | None, timeout: float,
                  ) -> AsyncIterator[Client]:
    """An initialized MCP client for `target`; errors inside the block come out as `ServerError`."""
    statuses: list[int] = []
    try:
        if target.transport == "stdio":
            server = StdioServerParameters(command=target.command or "", args=target.args)
            async with Client(server, read_timeout_seconds=timeout, cache=None, client_info=CLIENT_INFO) as client:
                yield client
        elif target.transport == "sse":
            def factory(headers=None, timeout=None, auth=None):  # the SDK's McpHttpClientFactory
                return http_client(transport, headers, statuses, timeout or TIMEOUT, auth)

            async with Client(sse_client(target.url or "", headers=target.headers, timeout=timeout,
                                         httpx_client_factory=factory),
                              read_timeout_seconds=timeout, cache=None, client_info=CLIENT_INFO) as client:
                yield client
        else:
            async with (http_client(transport, target.headers, statuses, timeout) as http,
                        Client(streamable_http_client(target.url or "", http_client=http),
                               read_timeout_seconds=timeout, cache=None, client_info=CLIENT_INFO) as client):
                yield client
    except ServerError:
        raise
    except Exception as exc:  # any transport, protocol or server failure becomes a ServerError
        if 401 in statuses:
            raise AuthRequired("The server refused the credentials (HTTP 401); sign in again.") from exc
        raise ServerError(describe(exc, statuses)) from exc


def describe(exc: BaseException, statuses: list[int] = ()) -> str:
    """A short message for an error, without secrets (no headers, no bodies)."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    failed = [s for s in statuses if s >= 400]
    if failed:
        return f"The server answered HTTP {failed[-1]}."
    if isinstance(exc, TimeoutError | httpx2.TimeoutException):
        return "The server did not answer in time."
    if isinstance(exc, httpx2.ConnectError):
        return "Cannot connect to the server."
    if isinstance(exc, MCPError):
        return f"MCP error {exc.code}: {exc.message}"[:300]
    return f"{type(exc).__name__}: {exc}"[:300]


async def list_tools(target: Target, transport: httpx2.AsyncBaseTransport | None = None) -> list[Tool]:
    try:
        with anyio.fail_after(TIMEOUT):
            async with session(target, transport, TIMEOUT) as client:
                tools, cursor = [], None
                for _ in range(MAX_TOOL_PAGES):
                    page = await client.list_tools(cursor=cursor)
                    tools += page.tools
                    if not (cursor := page.next_cursor):
                        break
                return tools
    except TimeoutError as exc:
        raise ServerError(describe(exc)) from exc


async def call_tool(target: Target, name: str, arguments: dict,
                    transport: httpx2.AsyncBaseTransport | None = None) -> ToolText:
    try:
        with anyio.fail_after(CALL_TIMEOUT):
            async with session(target, transport, CALL_TIMEOUT) as client:
                result = await client.call_tool(name, arguments)
    except TimeoutError as exc:
        raise ServerError(describe(exc)) from exc
    return ToolText(truncate(result_text(result)), bool(result.is_error))


def result_text(result: CallToolResult) -> str:
    """Text blocks joined; structured content as JSON when there is no text; other blocks named."""
    parts = []
    for block in result.content:
        text = getattr(block, "text", None) or getattr(getattr(block, "resource", None), "text", None)
        parts.append(text if text is not None else f"[{block.type} content omitted]")
    if not any(parts) and result.structured_content is not None:
        parts = [json.dumps(result.structured_content, ensure_ascii=False, default=str)]
    return "\n".join(parts)


def truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[truncated: {len(text) - limit} more characters]"


# --- OAuth (MCP authorization) ------------------------------------------------------------------------------


@dataclass
class OAuthClient:
    """This app's registration with one authorization server, and where to use it. Stored encrypted."""

    client_id: str
    client_secret: str | None
    auth_method: str | None  # token endpoint auth: client_secret_basic | client_secret_post | none
    issuer: str | None
    authorization_endpoint: str
    token_endpoint: str
    resource: str
    redirect_uri: str
    scope: str | None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> OAuthClient:
        return cls(**json.loads(raw))


async def prepare_oauth(server_url: str, redirect_uri: str, private_ok: bool, known: OAuthClient | None = None,
                        preregistered: tuple[str, str | None] | None = None,
                        transport: httpx2.AsyncBaseTransport | None = None) -> OAuthClient:
    """Discover the authorization server of `server_url` and get a client for it: `preregistered`
    (client id, secret) when given, else `known` when it was registered with the same server and redirect,
    else a new dynamic registration. Every URL fetched passes `vet_url(url, private_ok)` first, and so do the
    authorization server's token endpoint (used later) and authorization endpoint."""
    try:
        with anyio.fail_after(TIMEOUT):
            async with http_client(transport) as http:
                async def send(request: httpx2.Request) -> httpx2.Response:
                    await vet_url(str(request.url), private_ok)
                    return await http.send(request)

                client = await _prepare(send, server_url, redirect_uri, known, preregistered)
                for url in (client.token_endpoint, client.authorization_endpoint):
                    await vet_url(url, private_ok)
                return client
    except ServerError:
        raise
    except Exception as exc:
        raise ServerError(f"OAuth discovery or registration failed: {describe(exc)}") from exc


async def _prepare(send, server_url: str, redirect_uri: str, known: OAuthClient | None,
                   preregistered: tuple[str, str | None] | None) -> OAuthClient:
    # 1. An unauthenticated request: a 401 may name the resource metadata and the scope.
    probe = await send(httpx2.Request("POST", server_url, json={"jsonrpc": "2.0", "id": 0, "method": "ping"},
                                      headers={"accept": "application/json, text/event-stream"}))
    challenged = probe.status_code in (401, 403)
    hint = extract_resource_metadata_from_www_auth(probe) if challenged else None
    # 2. RFC 9728 protected resource metadata -> which authorization server.
    prm = None
    for url in build_protected_resource_metadata_discovery_urls(hint, server_url):
        if prm := await handle_protected_resource_response(await send(create_oauth_metadata_request(url))):
            break
    issuer = str(prm.authorization_servers[0]) if prm else None
    # 3. RFC 8414 authorization server metadata.
    asm = None
    for url in build_oauth_authorization_server_metadata_discovery_urls(issuer, server_url):
        ok, asm = await handle_auth_metadata_response(await send(create_oauth_metadata_request(url)))
        if not ok or asm:
            break
    if asm is None:
        raise ServerError("The server publishes no OAuth authorization server metadata.")
    if issuer and not issuers_match(str(asm.issuer), issuer):
        raise ServerError("The authorization server metadata names another issuer.")
    issuer = str(asm.issuer)
    resource = resource_url_from_server_url(server_url)
    if prm and check_resource_allowed(requested_resource=resource, configured_resource=str(prm.resource)):
        resource = str(prm.resource)
    scope = get_client_metadata_scopes(extract_scope_from_www_auth(probe) if challenged else None, prm, asm,
                                       ["authorization_code", "refresh_token"])
    endpoints = dict(issuer=issuer, authorization_endpoint=str(asm.authorization_endpoint),
                     token_endpoint=str(asm.token_endpoint), resource=resource, redirect_uri=redirect_uri, scope=scope)
    # 4. The client: pre-registered, already registered, or RFC 7591 dynamic registration.
    if preregistered:
        client_id, secret = preregistered
        methods = asm.token_endpoint_auth_methods_supported or ["client_secret_basic"]
        method = "none" if not secret else "client_secret_basic" if "client_secret_basic" in methods \
            else "client_secret_post"
        return OAuthClient(client_id=client_id, client_secret=secret, auth_method=method, **endpoints)
    if known and known.issuer == issuer and known.redirect_uri == redirect_uri:
        return OAuthClient(client_id=known.client_id, client_secret=known.client_secret,
                           auth_method=known.auth_method, **endpoints)
    if asm.registration_endpoint is None:
        raise ServerError("The authorization server offers no dynamic client registration: enter a pre-registered "
                          "client as the token (client_id:client_secret).")
    metadata = OAuthClientMetadata(redirect_uris=[redirect_uri], client_name=CLIENT_INFO.name, scope=scope,
                                   grant_types=["authorization_code", "refresh_token"], response_types=["code"],
                                   token_endpoint_auth_method="none")
    registered = await handle_registration_response(
        await send(create_client_registration_request(asm, metadata, issuer)))
    return OAuthClient(client_id=registered.client_id, client_secret=registered.client_secret,
                       auth_method=registered.token_endpoint_auth_method, **endpoints)


def authorize_url(client: OAuthClient, state: str, code_challenge: str) -> str:
    params = {"response_type": "code", "client_id": client.client_id, "redirect_uri": client.redirect_uri,
              "state": state, "code_challenge": code_challenge, "code_challenge_method": "S256",
              "resource": client.resource}
    if client.scope:
        params["scope"] = client.scope
    separator = "&" if urlparse(client.authorization_endpoint).query else "?"
    return f"{client.authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_code(client: OAuthClient, code: str, code_verifier: str, private_ok: bool,
                        transport: httpx2.AsyncBaseTransport | None = None) -> OAuthToken:
    return await _token_request(client, {"grant_type": "authorization_code", "code": code,
                                         "redirect_uri": client.redirect_uri, "code_verifier": code_verifier},
                                private_ok, transport)


async def refresh(client: OAuthClient, refresh_token: str, private_ok: bool,
                  transport: httpx2.AsyncBaseTransport | None = None) -> OAuthToken:
    token = await _token_request(client, {"grant_type": "refresh_token", "refresh_token": refresh_token},
                                 private_ok, transport)
    token.refresh_token = token.refresh_token or refresh_token  # RFC 6749 §6: the server may keep it
    return token


async def _token_request(client: OAuthClient, data: dict, private_ok: bool,
                         transport: httpx2.AsyncBaseTransport | None) -> OAuthToken:
    await vet_url(client.token_endpoint, private_ok)
    data = {**data, "client_id": client.client_id, "resource": client.resource}
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if client.client_secret and client.auth_method == "client_secret_basic":
        pair = f"{quote(client.client_id, safe='')}:{quote(client.client_secret, safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    elif client.client_secret:
        data["client_secret"] = client.client_secret
    try:
        with anyio.fail_after(TIMEOUT):
            async with http_client(transport) as http:
                response = await http.post(client.token_endpoint, data=data, headers=headers)
                if response.status_code not in (200, 201):
                    raise ServerError(f"The token endpoint answered HTTP {response.status_code}.")
                return await handle_token_response_scopes(response)
    except ServerError:
        raise
    except Exception as exc:
        raise ServerError(f"Token request failed: {describe(exc)}") from exc
