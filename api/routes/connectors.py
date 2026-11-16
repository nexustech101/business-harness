"""MCP connectors: the store, installed connectors, their tools, and OAuth for remote servers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from api.deps import ClientDep, ConnectorsDep, business_owner, require_api_key
from api.errors import responses
from business.connectors import ConnectorError
from business.schema import ConnectorCreate, ConnectorInfo, ConnectorListing, ConnectorTool, OAuthStart
from core.schema import Envelope

router = APIRouter(prefix="/v1/connectors", tags=["Connectors"], responses=responses(401))
keyed = [Depends(require_api_key)]


def _found(value):
    if value is None:
        raise HTTPException(404, "Connector not found.")
    return value


@router.get("/catalog", response_model=Envelope[list[ConnectorListing]], dependencies=keyed)
def catalog(hub: ConnectorsDep) -> Envelope[list[ConnectorListing]]:
    """The connector store, featured first."""
    return Envelope(data=hub.catalog())


@router.get("", response_model=Envelope[list[ConnectorInfo]], dependencies=keyed)
def list_connectors(key: ClientDep, hub: ConnectorsDep) -> Envelope[list[ConnectorInfo]]:
    return Envelope(data=hub.list(business_owner(key)))


@router.post("", response_model=Envelope[ConnectorInfo], status_code=201, dependencies=keyed,
             responses=responses(403, 422))
async def add_connector(body: ConnectorCreate, key: ClientDep, hub: ConnectorsDep) -> Envelope[ConnectorInfo]:
    """
    Add a connector from the store (`listing_id`) or by hand, then check it (the result is in `status`).
    stdio connectors run a command on the server: admin keys only.
    """
    return Envelope(data=await hub.add(business_owner(key), body, admin=key.is_admin))


@router.delete("/{connector_id}", status_code=204, dependencies=keyed, responses=responses(404))
def remove_connector(connector_id: str, key: ClientDep, hub: ConnectorsDep) -> Response:
    _found(hub.remove(business_owner(key), connector_id) or None)
    return Response(status_code=204)


@router.post("/{connector_id}/check", response_model=Envelope[ConnectorInfo], dependencies=keyed,
             responses=responses(404))
async def check(connector_id: str, key: ClientDep, hub: ConnectorsDep) -> Envelope[ConnectorInfo]:
    """Connect and list its tools; `status`, `error` and `tool_count` are updated."""
    return Envelope(data=_found(await hub.check(business_owner(key), connector_id)))


@router.get("/{connector_id}/tools", response_model=Envelope[list[ConnectorTool]], dependencies=keyed,
            responses=responses(404))
async def tools(connector_id: str, key: ClientDep, hub: ConnectorsDep) -> Envelope[list[ConnectorTool]]:
    owner = business_owner(key)
    _found(hub.get(owner, connector_id))
    return Envelope(data=await hub.tools(owner, [connector_id]))


@router.post("/{connector_id}/oauth", response_model=Envelope[OAuthStart], dependencies=keyed,
             responses=responses(404, 422, 502))
async def start_oauth(connector_id: str, key: ClientDep, hub: ConnectorsDep) -> Envelope[OAuthStart]:
    """Start the provider's sign-in; open `authorize_url` in the browser."""
    return Envelope(data=_found(await hub.start_oauth(business_owner(key), connector_id)))


@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(hub: ConnectorsDep, state: str = Query(...), code: str | None = Query(None),
                         error: str | None = Query(None)) -> RedirectResponse:
    """The provider's redirect (no API key: the browser follows it). Back to the dashboard either way."""
    if error or not code:
        return RedirectResponse(f"/connectors?oauth_error={error or 'no_code'}", status_code=303)
    try:
        connector = await hub.finish_oauth(state, code)
    except ConnectorError:
        return RedirectResponse("/connectors?oauth_error=expired", status_code=303)
    return RedirectResponse(f"/connectors?connected={connector.id}", status_code=303)
