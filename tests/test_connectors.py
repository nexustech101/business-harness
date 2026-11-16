"""Connectors: the store catalog, `ConnectorHub` against a real in-process MCP server (the `mcp` SDK's
`MCPServer` over streamable HTTP, reached through an httpx2 ASGI transport), the OAuth flow against a fake
authorization server, and the routes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import socket
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
import uvicorn
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from business import catalog
from business.connectors import ConnectorError, ConnectorHub, InvalidConnector, NotAllowed
from business.mcp_client import MAX_RESULT_CHARS, result_text, truncate
from business.schema import ConnectorCreate

BASE = "http://127.0.0.1"
SERVER = f"{BASE}/mcp"
PUBLIC = "http://localhost:8000"
REDIRECT = f"{PUBLIC}/v1/connectors/oauth/callback"


def mcp_server() -> MCPServer:
    server = MCPServer("crm")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def lookup(customer: str) -> str:
        """Find a customer."""
        return f"found {customer}"

    @server.tool()
    def charge(amount: int) -> str:
        """Charge a card."""
        if amount < 0:
            raise ValueError("negative amount")
        return f"charged {amount}"

    return server


class Provider:
    """The MCP server at /mcp behind a bearer check (`tokens`: accepted tokens; None = open), and a fake OAuth
    authorization server: RFC 9728 and 8414 metadata, RFC 7591 registration, authorization code + PKCE, refresh."""

    def __init__(self, tokens: set[str] | None = None, registration: bool = True, expires_in: int | None = 3600):
        self.tokens, self.registration, self.expires_in = tokens, registration, expires_in
        self.seen_auth: list[str] = []
        self.codes: dict[str, dict] = {}
        self.refresh_tokens: dict[str, str] = {}
        self.token_requests: list[dict] = []
        self.mcp = mcp_server().streamable_http_app(
            stateless_http=True, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
        self.auth_server = Starlette(routes=[
            Route("/.well-known/oauth-protected-resource/mcp", self.resource_metadata),
            Route("/.well-known/oauth-authorization-server", self.server_metadata),
            Route("/register", self.register, methods=["POST"]),
            Route("/token", self.token, methods=["POST"]),
        ])

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/slow":
            await asyncio.sleep(5)
        if scope["type"] == "http" and scope["path"] == "/mcp":
            auth = dict(scope["headers"]).get(b"authorization", b"").decode()
            self.seen_auth.append(auth)
            if self.tokens is not None and auth.removeprefix("Bearer ") not in self.tokens:
                challenge = f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"'
                response = JSONResponse({"error": "invalid_token"}, 401, headers={"WWW-Authenticate": challenge})
                return await response(scope, receive, send)
            return await self.mcp(scope, receive, send)
        return await self.auth_server(scope, receive, send)

    def lifespan(self):
        return self.mcp.router.lifespan_context(self.mcp)

    async def resource_metadata(self, request: Request):
        return JSONResponse({"resource": SERVER, "authorization_servers": [BASE], "scopes_supported": ["crm"]})

    async def server_metadata(self, request: Request):
        body = {"issuer": BASE, "authorization_endpoint": f"{BASE}/authorize", "token_endpoint": f"{BASE}/token",
                "code_challenge_methods_supported": ["S256"]}
        if self.registration:
            body["registration_endpoint"] = f"{BASE}/register"
        return JSONResponse(body)

    async def register(self, request: Request):
        metadata = await request.json()
        return JSONResponse({**metadata, "client_id": "dyn-client", "token_endpoint_auth_method": "none"}, 201)

    def approve(self, authorize_url: str) -> tuple[str, str]:
        """The user consents: a code bound to the request's client, redirect and PKCE challenge."""
        params = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
        code = secrets.token_urlsafe(8)
        self.codes[code] = params
        return params["state"], code

    def issue(self) -> dict:
        access, refresh = secrets.token_urlsafe(8), secrets.token_urlsafe(8)
        self.tokens.add(access)
        self.refresh_tokens[refresh] = access
        body = {"access_token": access, "token_type": "Bearer", "refresh_token": refresh, "scope": "crm"}
        return body if self.expires_in is None else {**body, "expires_in": self.expires_in}

    async def token(self, request: Request):
        form = dict(await request.form())
        self.token_requests.append({**form, "authorization": request.headers.get("authorization")})
        if form["grant_type"] == "refresh_token":
            await asyncio.sleep(0.05)  # a real round trip: concurrent operations overlap here
            if self.refresh_tokens.pop(form["refresh_token"], None) is None:  # rotating: each one works once
                return JSONResponse({"error": "invalid_grant"}, 400)
            return JSONResponse(self.issue())
        grant = self.codes.pop(form["code"], None)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=")
        if (grant is None or challenge.decode() != grant["code_challenge"]
                or form["redirect_uri"] != grant["redirect_uri"] or form["client_id"] != grant["client_id"]):
            return JSONResponse({"error": "invalid_grant"}, 400)
        return JSONResponse(self.issue())


def make_hub(tmp_path, provider: Provider, key: bytes | None = b"", private: bool = True) -> ConnectorHub:
    """`private`: the in-process provider is at http://127.0.0.1, which only trusted connectors may reach, so by
    default every connector is treated as trusted (`allow_private_urls`); the URL rule tests turn it off."""
    hub = ConnectorHub(tmp_path / "business.db", Fernet.generate_key() if key == b"" else key, PUBLIC)
    hub.http_transport = httpx2.ASGITransport(provider)
    hub.allow_private_urls = private
    return hub


def run(provider: Provider, scenario):
    """Run `scenario()` while the provider's MCP session manager is up."""
    async def main():
        async with provider.lifespan():
            return await scenario()
    return asyncio.run(main())


def by_hand(**fields) -> ConnectorCreate:
    return ConnectorCreate(**{"name": "CRM", "url": SERVER, **fields})


# --- catalog -------------------------------------------------------------------------------------------


def test_catalog_integrity(tmp_path):
    ids = [item.id for item in catalog.LISTINGS]
    assert len(ids) == len(set(ids))
    assert {"workspace-database", "google-drive", "google-docs", "google-sheets", "gmail", "google-calendar",
            "google-workspace", "dropbox", "box", "google-ads", "microsoft-365", "hubspot", "salesforce",
            "gohighlevel", "snowflake", "stripe", "square", "slack", "notion", "atlassian", "github", "n8n",
            "supabase", "databricks", "shopify-catalog"} <= set(ids)
    for item in catalog.LISTINGS:
        assert item.tagline and item.auth in ("none", "bearer", "oauth")
        if item.builtin:  # runs in this app: nothing to connect to
            assert (item.transport, item.url, item.auth, item.docs_url) == ("builtin", None, "none", "")
            continue
        assert item.transport != "builtin" and item.docs_url.startswith("https://")
        assert item.url is None or item.url.startswith("https://")
        assert item.url or "url" in item.description.lower() or "http" in item.description
    assert 6 <= sum(item.featured for item in catalog.LISTINGS) <= 8
    assert {"google-drive", "dropbox", "box"} <= {i.id for i in catalog.LISTINGS if i.category == "Storage"}
    store = ConnectorHub(tmp_path / "b.db", None, PUBLIC).catalog()
    order = [(item.builtin, item.featured) for item in store]
    assert order == sorted(order, reverse=True)  # built-in apps, then featured, then the rest


def test_result_text_and_truncation():
    structured = CallToolResult(content=[], structured_content={"total": 3})
    assert json.loads(result_text(structured)) == {"total": 3}
    joined = CallToolResult(content=[TextContent(type="text", text="a"), TextContent(type="text", text="b")])
    assert result_text(joined) == "a\nb"
    long = truncate("x" * (MAX_RESULT_CHARS + 5))
    assert long.endswith("[truncated: 5 more characters]") and long.startswith("x" * MAX_RESULT_CHARS)


# --- install, check, tools, call ----------------------------------------------------------------------------


def test_add_by_hand_check_tools_and_call(tmp_path):
    provider = Provider()
    hub = make_hub(tmp_path, provider)

    async def scenario():
        info = await hub.add("1", by_hand(), admin=False)
        assert (info.status, info.tool_count, info.error, info.has_secret) == ("connected", 2, None, False)
        assert info.checked_at is not None and hub.list("1")[0].id == info.id
        tools = {t.name: t for t in await hub.tools("1", [info.id, info.id, "unknown"])}
        assert {n: t.read_only for n, t in tools.items()} == {"lookup": True, "charge": False}
        assert tools["lookup"].description == "Find a customer." and "customer" in tools["lookup"].input_schema[
            "properties"]
        ok = await hub.call("1", info.id, "lookup", {"customer": "acme"})
        failed = await hub.call("1", info.id, "charge", {"amount": -1})
        unknown_tool = await hub.call("1", info.id, "refund", {})
        unknown = await hub.call("1", "nope", "lookup", {})
        return ok, failed, unknown_tool, unknown

    ok, failed, unknown_tool, unknown = run(provider, scenario)
    assert (ok.text, ok.is_error) == ("found acme", False)
    assert failed.is_error and unknown_tool.is_error and unknown.is_error


def test_unreachable_server_is_recorded_not_raised(tmp_path):
    provider = Provider()
    hub = make_hub(tmp_path, provider)

    async def scenario():
        info = await hub.add("1", by_hand(url=f"{BASE}/missing"), admin=False)
        result = await hub.call("1", info.id, "lookup", {"customer": "x"})
        return info, result, await hub.tools("1", [info.id])

    info, result, tools = run(provider, scenario)
    assert info.status == "error" and "404" in info.error and info.tool_count == 0
    assert result.is_error and "failed" in result.text and tools == []


def test_every_network_call_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("business.mcp_client.TIMEOUT", 0.3)
    provider = Provider()
    hub = make_hub(tmp_path, provider)
    info = run(provider, lambda: hub.add("1", by_hand(url=f"{BASE}/slow"), admin=False))
    assert (info.status, info.error) == ("error", "The server did not answer in time.")


def test_without_a_configured_key_one_is_generated_on_first_need(tmp_path):
    provider = Provider(tokens={"tok-good-123"})
    key_file = tmp_path / "secrets.key"
    hub = ConnectorHub(tmp_path / "business.db", None, PUBLIC, key_file=key_file)
    hub.http_transport, hub.allow_private_urls = httpx2.ASGITransport(provider), True
    assert hub.list("1") == [] and not key_file.exists()  # nothing to encrypt yet: no key written
    again = ConnectorHub(tmp_path / "business.db", None, PUBLIC, key_file=key_file)  # as after a restart
    again.http_transport, again.allow_private_urls = httpx2.ASGITransport(provider), True

    async def scenario():
        good = await hub.add("1", by_hand(name="Paid", auth="bearer", token="tok-good-123"), admin=False)
        return good, key_file.read_bytes(), await again.check("1", good.id)

    good, key, rechecked = run(provider, scenario)
    assert good.status == "connected" and good.has_secret
    assert b"tok-good-123" not in (tmp_path / "business.db").read_bytes()
    assert rechecked.status == "connected" and key_file.read_bytes() == key  # the same key was read back
    keyless = ConnectorHub(tmp_path / "other.db", None, PUBLIC)  # neither a key nor a key file: still refused
    with pytest.raises(InvalidConnector, match="BUSINESS_SECRETS_KEY"):
        asyncio.run(keyless.add("1", by_hand(auth="bearer", token="t"), admin=True))


def test_bearer_token_sent_wrong_token_needs_auth_and_encrypted_at_rest(tmp_path):
    provider = Provider(tokens={"tok-good-123"})
    hub = make_hub(tmp_path, provider)

    async def scenario():
        good = await hub.add("1", by_hand(auth="bearer", token="tok-good-123"), admin=False)
        bad = await hub.add("1", by_hand(name="Bad", auth="bearer", token="tok-wrong-456"), admin=False)
        return good, bad, await hub.call("1", bad.id, "lookup", {"customer": "x"})

    good, bad, call = run(provider, scenario)
    assert good.status == "connected" and good.has_secret and "Bearer tok-good-123" in provider.seen_auth
    assert bad.status == "needs_auth" and call.is_error and "sign-in" in call.text
    assert "tok-good" not in good.model_dump_json()
    raw = (tmp_path / "business.db").read_bytes()
    assert b"tok-good-123" not in raw and b"tok-wrong-456" not in raw
    with sqlite3.connect(tmp_path / "business.db") as conn:
        assert all(b"tok-" not in secret for (secret,) in conn.execute("SELECT secret FROM connectors"))


def test_add_from_listing(tmp_path):
    provider = Provider(tokens={"n8n-token"})
    hub = make_hub(tmp_path, provider)

    async def scenario():
        stripe = await hub.add("1", ConnectorCreate(listing_id="stripe", name="Stripe"), admin=False)
        with pytest.raises(InvalidConnector, match="no fixed server URL"):
            await hub.add("1", ConnectorCreate(listing_id="n8n", name="n8n"), admin=False)
        n8n = await hub.add("1", ConnectorCreate(listing_id="n8n", name="n8n", url=SERVER, token="n8n-token"),
                            admin=False)
        keyed = await hub.add("1", ConnectorCreate(listing_id="stripe", name="Stripe key", auth="bearer",
                                                   token="rk_agent"), admin=False)
        with pytest.raises(InvalidConnector, match="Unknown store listing"):
            await hub.add("1", ConnectorCreate(listing_id="nope", name="x"), admin=False)
        return stripe, n8n, keyed

    stripe, n8n, keyed = run(provider, scenario)
    # copied from the listing: no OAuth tokens yet, so no network call and needs_auth
    assert (stripe.listing_id, stripe.url, stripe.auth, stripe.status) == (
        "stripe", "https://mcp.stripe.com", "oauth", "needs_auth")
    assert (n8n.auth, n8n.status, n8n.tool_count) == ("bearer", "connected", 2)
    assert (keyed.auth, keyed.url, keyed.has_secret) == ("bearer", "https://mcp.stripe.com", True)


def test_invalid_requests_and_stdio_admin_only(tmp_path):
    provider = Provider()
    hub = make_hub(tmp_path, provider)
    keyless = make_hub(tmp_path / "keyless", provider, key=None)

    async def scenario():
        with pytest.raises(NotAllowed):
            await hub.add("1", ConnectorCreate(name="local", transport="stdio", command="echo"), admin=False)
        cases = [
            (hub, ConnectorCreate(name="x")),  # remote without url
            (hub, by_hand(url="ftp://example.com")),
            (hub, by_hand(auth="bearer")),  # bearer without token
            (hub, by_hand(token="t")),  # token with auth none
            (hub, ConnectorCreate(name="x", transport="stdio")),  # stdio without command
            (hub, ConnectorCreate(name="x", transport="stdio", command="srv", auth="bearer", token="t")),
            (keyless, by_hand(auth="bearer", token="t")),  # a secret without BUSINESS_SECRETS_KEY
            (keyless, by_hand(auth="oauth")),
        ]
        for target, request in cases:
            with pytest.raises(InvalidConnector):
                await target.add("1", request, admin=True)
        return await keyless.add("1", by_hand(), admin=False)

    assert run(provider, scenario).status == "connected"  # no secret: fine without a key
    assert hub.list("1") == []


def test_sse_transport(tmp_path):
    """SSE needs a real socket: the ASGI test transport does not stream the long-lived event stream."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mcp_server().sse_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    hub = ConnectorHub(tmp_path / "business.db", None, PUBLIC)

    async def scenario():
        info = await hub.add("1", ConnectorCreate(name="sse", transport="sse", url=f"http://127.0.0.1:{port}/sse"),
                             admin=True)
        return info, await hub.call("1", info.id, "lookup", {"customer": "acme"})

    try:
        info, result = asyncio.run(scenario())
    finally:
        server.should_exit = True
        thread.join(5)
    assert (info.status, info.tool_count) == ("connected", 2)
    assert (result.text, result.is_error) == ("found acme", False)


def test_stdio_connector_for_admin(tmp_path):
    script = tmp_path / "server.py"
    script.write_text("from mcp.server.mcpserver import MCPServer\n"
                      "server = MCPServer('local')\n"
                      "@server.tool()\n"
                      "def ping() -> str:\n"
                      "    return 'pong'\n"
                      "server.run('stdio')\n")
    hub = ConnectorHub(tmp_path / "business.db", None, PUBLIC)

    async def scenario():
        info = await hub.add("1", ConnectorCreate(name="local", transport="stdio", command=sys.executable,
                                                  args=[str(script)]), admin=True)
        return info, await hub.call("1", info.id, "ping", {})

    info, result = asyncio.run(scenario())
    assert (info.status, info.tool_count, info.url, info.command) == ("connected", 1, None, sys.executable)
    assert (result.text, result.is_error) == ("pong", False)


def test_owner_isolation_and_remove(tmp_path):
    provider = Provider()
    hub = make_hub(tmp_path, provider)

    async def scenario():
        info = await hub.add("1", by_hand(auth="oauth"), admin=False)
        other = (hub.list("2"), hub.get("2", info.id), await hub.check("2", info.id),
                 await hub.tools("2", [info.id]), (await hub.call("2", info.id, "lookup", {})).is_error,
                 await hub.start_oauth("2", info.id), hub.remove("2", info.id))
        return info, other

    info, other = run(provider, scenario)
    assert other == ([], None, None, [], True, None, False)
    assert hub.get("1", info.id) is not None
    assert hub.remove("1", info.id) and hub.list("1") == [] and not hub.remove("1", info.id)


# --- OAuth ------------------------------------------------------------------------------------------------


def test_oauth_flow_dynamic_registration(tmp_path):
    provider = Provider(tokens=set())
    hub = make_hub(tmp_path, provider)

    async def scenario():
        info = await hub.add("1", by_hand(auth="oauth"), admin=False)
        assert info.status == "needs_auth" and not info.has_secret
        start = await hub.start_oauth("1", info.id)
        state, code = provider.approve(start.authorize_url)
        with sqlite3.connect(tmp_path / "business.db") as conn:
            (stored,) = conn.execute("SELECT connector_id FROM connector_oauth_states WHERE state = ?",
                                     (state,)).fetchone()
        assert stored == info.id
        with pytest.raises(ConnectorError):
            await hub.finish_oauth("unknown-state", code)
        done = await hub.finish_oauth(state, code)
        with pytest.raises(ConnectorError):  # a state is used once
            await hub.finish_oauth(state, code)
        return start, done, await hub.call("1", info.id, "lookup", {"customer": "acme"})

    start, done, result = run(provider, scenario)
    params = parse_qs(urlparse(start.authorize_url).query)
    assert start.authorize_url.startswith(f"{BASE}/authorize?")
    assert params["client_id"] == ["dyn-client"] and params["redirect_uri"] == [REDIRECT]
    assert params["code_challenge_method"] == ["S256"] and params["resource"] == [SERVER]
    assert params["scope"] == ["crm"]
    assert (done.status, done.tool_count, done.has_secret) == ("connected", 2, True)
    assert result.text == "found acme"
    raw = (tmp_path / "business.db").read_bytes()
    assert not any(token.encode() in raw for token in provider.tokens)


def test_oauth_refresh_when_expired(tmp_path):
    provider = Provider(tokens=set(), expires_in=0)
    hub = make_hub(tmp_path, provider)

    async def scenario():
        info = await hub.add("1", by_hand(auth="oauth"), admin=False)
        start = await hub.start_oauth("1", info.id)
        await hub.finish_oauth(*provider.approve(start.authorize_url))  # checks: the token is already expired
        provider.refresh_tokens.clear()  # the next refresh fails
        return await hub.check("1", info.id)

    after = run(provider, scenario)
    grants = [r["grant_type"] for r in provider.token_requests]
    assert grants == ["authorization_code", "refresh_token", "refresh_token"]
    assert after.status == "needs_auth" and "sign in again" in after.error


def test_oauth_expired_state_and_preregistered_client(tmp_path):
    provider = Provider(tokens=set(), registration=False)
    hub = make_hub(tmp_path, provider)

    async def scenario():
        plain = await hub.add("1", by_hand(auth="oauth"), admin=False)
        with pytest.raises(ConnectorError, match="no dynamic client registration"):
            await hub.start_oauth("1", plain.id)
        with pytest.raises(InvalidConnector):
            await hub.start_oauth("1", (await hub.add("1", by_hand(name="open"), admin=False)).id)
        info = await hub.add("1", by_hand(auth="oauth", token="client-x:secret-y"), admin=False)
        state, code = provider.approve((await hub.start_oauth("1", info.id)).authorize_url)
        with sqlite3.connect(tmp_path / "business.db") as conn:
            conn.execute("UPDATE connector_oauth_states SET expires_at = 0")
        with pytest.raises(ConnectorError, match="expired"):
            await hub.finish_oauth(state, code)
        state, code = provider.approve((await hub.start_oauth("1", info.id)).authorize_url)
        provider.codes[code]["client_id"] = "client-x"
        return await hub.finish_oauth(state, code)

    done = run(provider, scenario)
    assert done.status == "connected"
    (exchange,) = [r for r in provider.token_requests if r["grant_type"] == "authorization_code"]
    assert exchange["client_id"] == "client-x" and "client_secret" not in exchange
    assert base64.b64decode(exchange["authorization"].removeprefix("Basic ")) == b"client-x:secret-y"


def test_oauth_concurrent_refresh_spends_the_refresh_token_once(tmp_path, monkeypatch):
    provider = Provider(tokens=set())
    hub = make_hub(tmp_path, provider)
    clock = [1_000_000.0]
    monkeypatch.setattr("business.connectors.time", SimpleNamespace(time=lambda: clock[0]))

    async def scenario():
        info = await hub.add("1", by_hand(auth="oauth"), admin=False)
        await hub.finish_oauth(*provider.approve((await hub.start_oauth("1", info.id)).authorize_url))
        clock[0] += 7200  # the access token has expired
        return await asyncio.gather(*(hub.call("1", info.id, "lookup", {"customer": str(n)}) for n in range(3)))

    results = run(provider, scenario)
    assert [r.text for r in results] == ["found 0", "found 1", "found 2"]
    assert [r["grant_type"] for r in provider.token_requests] == ["authorization_code", "refresh_token"]


def test_oauth_401_refreshes_once_even_without_expiry(tmp_path):
    provider = Provider(tokens=set(), expires_in=None)
    hub = make_hub(tmp_path, provider)

    async def scenario():
        info = await hub.add("1", by_hand(auth="oauth"), admin=False)
        await hub.finish_oauth(*provider.approve((await hub.start_oauth("1", info.id)).authorize_url))
        provider.tokens.clear()  # the server revokes the access token
        renewed = await hub.call("1", info.id, "lookup", {"customer": "acme"})
        provider.tokens.clear()
        provider.refresh_tokens.clear()  # ... and now the refresh token too
        return renewed, await hub.call("1", info.id, "lookup", {"customer": "acme"}), hub.get("1", info.id)

    renewed, refused, after = run(provider, scenario)
    assert (renewed.text, renewed.is_error) == ("found acme", False)
    assert refused.is_error and after.status == "needs_auth"
    assert [r["grant_type"] for r in provider.token_requests] == ["authorization_code", "refresh_token",
                                                                  "refresh_token"]


# --- URL rule ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://mcp.example.com/mcp", "https://127.0.0.1/mcp", "https://localhost/mcp",
                                 "https://169.254.169.254/latest", "https://10.1.2.3/mcp", "https://192.168.1.5/mcp",
                                 "https://[::1]/mcp", "https://[::ffff:127.0.0.1]/mcp", "https://0.0.0.0/mcp",
                                 "https://does-not-resolve.invalid/mcp", "ftp://example.com/x"])
def test_non_admin_keys_reach_only_public_https(tmp_path, url):
    hub = make_hub(tmp_path, Provider(), private=False)
    with pytest.raises(InvalidConnector):
        asyncio.run(hub.add("1", by_hand(url=url), admin=False))
    assert hub.list("1") == []


def test_public_https_allowed_and_admin_trusted(tmp_path, monkeypatch):
    async def public(host, port):
        return [(None, None, None, "", ("93.184.216.34", 0))]
    monkeypatch.setattr("business.mcp_client.anyio.getaddrinfo", public)
    provider = Provider(tokens={"tok"})
    hub = make_hub(tmp_path, provider, private=False)

    async def scenario():
        public_one = await hub.add("1", by_hand(url="https://mcp.example.com/mcp", auth="oauth"), admin=False)
        # its 401 names resource metadata at http://127.0.0.1: refused for a non-admin connector
        with pytest.raises(InvalidConnector, match="admin keys"):
            await hub.start_oauth("1", public_one.id)
        local = await hub.add("1", by_hand(auth="bearer", token="tok"), admin=True)  # admin: http and loopback allowed, and remembered
        return public_one, local, await hub.check("1", local.id), await hub.call("1", local.id, "lookup",
                                                                                   {"customer": "a"})

    public_one, local, checked, result = run(provider, scenario)
    assert public_one.status == "needs_auth" and public_one.url == "https://mcp.example.com/mcp"
    assert (local.status, checked.status, result.text) == ("connected", "connected", "found a")
    assert provider.seen_auth  # the public connector's probe reached the server, nothing at 127.0.0.1 metadata


def test_admin_oauth_on_private_network(tmp_path):
    provider = Provider(tokens=set())
    hub = make_hub(tmp_path, provider, private=False)

    async def scenario():
        info = await hub.add("1", by_hand(auth="oauth"), admin=True)
        return await hub.finish_oauth(*provider.approve((await hub.start_oauth("1", info.id)).authorize_url))

    assert run(provider, scenario).status == "connected"


def test_url_rule_checked_again_on_every_connection(tmp_path):
    provider = Provider()
    hub = make_hub(tmp_path, provider, private=False)

    async def scenario():
        info = await hub.add("1", by_hand(), admin=True)
        with sqlite3.connect(tmp_path / "business.db") as conn:
            conn.execute("UPDATE connectors SET trusted = 0")  # e.g. a connector stored by a non-admin key
        return await hub.check("1", info.id), await hub.call("1", info.id, "lookup", {"customer": "a"})

    checked, result = run(provider, scenario)
    assert checked.status == "error" and "https" in checked.error
    assert result.is_error


# --- routes -------------------------------------------------------------------------------------------------


def route_app(hub: ConnectorHub, provider: Provider, admin: bool = False) -> FastAPI:
    from contextlib import asynccontextmanager

    from api.deps import require_api_key
    from api.errors import register
    from api.routes.connectors import router

    @asynccontextmanager
    async def lifespan(app):
        async with provider.lifespan():
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    register(app)
    app.state.connectors = hub
    app.dependency_overrides[require_api_key] = lambda: SimpleNamespace(id=7, name="k", is_admin=admin)
    return app


def test_routes(tmp_path):
    provider = Provider(tokens=set())
    hub = make_hub(tmp_path, provider)
    with TestClient(route_app(hub, provider)) as client:
        store = client.get("/v1/connectors/catalog").json()["data"]
        assert store[0]["builtin"] and store[1]["featured"] and len(store) == len(catalog.LISTINGS)
        assert client.post("/v1/connectors", json={"name": "x", "transport": "stdio", "command": "sh"}).status_code \
            == 403
        invalid = client.post("/v1/connectors", json={"name": "x"})
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_connector"
        added = client.post("/v1/connectors", json={"name": "CRM", "url": SERVER, "auth": "oauth"})
        assert added.status_code == 201 and added.json()["data"]["status"] == "needs_auth"
        cid = added.json()["data"]["id"]
        assert hub.list("7")[0].id == cid  # owner = business_owner(key) = key id
        start = client.post(f"/v1/connectors/{cid}/oauth").json()["data"]
        state, code = provider.approve(start["authorize_url"])
        callback = client.get("/v1/connectors/oauth/callback", params={"state": state, "code": code},
                              follow_redirects=False)
        assert callback.status_code == 303 and callback.headers["location"] == f"/connectors?connected={cid}"
        expired = client.get("/v1/connectors/oauth/callback", params={"state": state, "code": code},
                             follow_redirects=False)
        assert expired.headers["location"] == "/connectors?oauth_error=expired"
        tools = client.get(f"/v1/connectors/{cid}/tools").json()["data"]
        assert {t["name"]: t["read_only"] for t in tools} == {"lookup": True, "charge": False}
        assert client.post(f"/v1/connectors/{cid}/check").json()["data"]["status"] == "connected"
        assert client.get("/v1/connectors").json()["data"][0]["has_secret"] is True
        assert client.get("/v1/connectors/nope/tools").status_code == 404
        assert client.post("/v1/connectors/nope/oauth").status_code == 404
        assert client.delete(f"/v1/connectors/{cid}").status_code == 204
        assert client.delete(f"/v1/connectors/{cid}").status_code == 404


def test_nat64_addresses_are_judged_by_the_ipv4_address_they_reach():
    from business.mcp_client import UnsafeUrl, vet_url

    for url in ("https://[64:ff9b::a9fe:a9fe]/mcp", "https://[64:ff9b:1::7f00:1]/mcp"):  # 169.254.169.254, 127.0.0.1
        with pytest.raises(UnsafeUrl):
            asyncio.run(vet_url(url, private_ok=False))
    asyncio.run(vet_url("https://[64:ff9b::808:808]/mcp", private_ok=False))  # 8.8.8.8: public
