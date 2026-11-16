"""Assistants (one JSON spec each) and the approvals queue for their write actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.deps import BusinessDep, ClientDep, RateLimit, business_owner, require_api_key
from api.errors import responses
from business.schema import (
    Approval,
    ApprovalDecision,
    ApprovalStatus,
    AssistantContext,
    AssistantInfo,
    AssistantSpec,
    AssistantStatusRequest,
    RunRequest,
    RunResponse,
)
from core.schema import Envelope

router = APIRouter(tags=["Assistants"], dependencies=[Depends(require_api_key)], responses=responses(401))


def _found(value, what: str = "Assistant"):
    if value is None:
        raise HTTPException(404, f"{what} not found.")
    return value


@router.get("/v1/assistants/schema", response_model=Envelope[dict])
def spec_schema(business: BusinessDep) -> Envelope[dict]:
    """JSON Schema of an assistant spec: what `POST /v1/assistants` takes."""
    return Envelope(data=business.assistant_schema())


@router.get("/v1/assistants", response_model=Envelope[list[AssistantInfo]])
def list_assistants(key: ClientDep, business: BusinessDep) -> Envelope[list[AssistantInfo]]:
    return Envelope(data=business.assistants(business_owner(key)))


@router.post("/v1/assistants", response_model=Envelope[AssistantInfo], status_code=201, responses=responses(422))
def create_assistant(body: AssistantSpec, key: ClientDep, business: BusinessDep) -> Envelope[AssistantInfo]:
    """Create an assistant from its JSON spec. It starts as a `draft`; activate it to run it."""
    return Envelope(data=business.create_assistant(business_owner(key), body))


@router.get("/v1/assistants/{assistant_id}", response_model=Envelope[AssistantInfo], responses=responses(404))
def get_assistant(assistant_id: str, key: ClientDep, business: BusinessDep) -> Envelope[AssistantInfo]:
    return Envelope(data=_found(business.assistant(business_owner(key), assistant_id)))


@router.put("/v1/assistants/{assistant_id}", response_model=Envelope[AssistantInfo], responses=responses(404, 422))
def update_assistant(assistant_id: str, body: AssistantSpec, key: ClientDep,
                     business: BusinessDep) -> Envelope[AssistantInfo]:
    """Replace the spec; the status stays."""
    return Envelope(data=_found(business.update_assistant(business_owner(key), assistant_id, body)))


@router.put("/v1/assistants/{assistant_id}/status", response_model=Envelope[AssistantInfo], responses=responses(404))
def set_status(assistant_id: str, body: AssistantStatusRequest, key: ClientDep,
               business: BusinessDep) -> Envelope[AssistantInfo]:
    """Activate, pause, or return to draft."""
    return Envelope(data=_found(business.set_status(business_owner(key), assistant_id, body.status)))


@router.delete("/v1/assistants/{assistant_id}", status_code=204, responses=responses(404))
def delete_assistant(assistant_id: str, key: ClientDep, business: BusinessDep) -> Response:
    _found(business.delete_assistant(business_owner(key), assistant_id) or None)
    return Response(status_code=204)


@router.get("/v1/assistants/{assistant_id}/context", response_model=Envelope[AssistantContext],
            responses=responses(404))
async def context(assistant_id: str, key: ClientDep, business: BusinessDep) -> Envelope[AssistantContext]:
    """Exactly what the assistant's model receives before a task: context layers and offered tools."""
    return Envelope(data=_found(await business.context(business_owner(key), assistant_id)))


@router.post("/v1/assistants/{assistant_id}/run", response_model=Envelope[RunResponse],
             responses=responses(404, 409, 429, 503), dependencies=[Depends(RateLimit("assistant"))])
async def run(assistant_id: str, body: RunRequest, key: ClientDep, business: BusinessDep) -> Envelope[RunResponse]:
    """
    Give an active assistant a task. Read-only tool calls run; write calls follow its policy: `auto` runs,
    `ask` queues an approval (the assistant is told it is pending), `deny` refuses.
    """
    return Envelope(data=_found(await business.run(business_owner(key), assistant_id, body)))


@router.get("/v1/approvals", response_model=Envelope[list[Approval]])
def approvals(key: ClientDep, business: BusinessDep,
              status: ApprovalStatus | None = Query(None, description="Only this status; newest first.")
              ) -> Envelope[list[Approval]]:
    return Envelope(data=business.approvals(business_owner(key), status))


@router.post("/v1/approvals/{approval_id}/decision", response_model=Envelope[Approval],
             responses=responses(404, 409, 422))
async def decide(approval_id: str, body: ApprovalDecision, key: ClientDep,
                 business: BusinessDep) -> Envelope[Approval]:
    """Approve (the call runs now; `always` also sets the tool to `auto` for that assistant) or reject."""
    return Envelope(data=_found(await business.decide(business_owner(key), approval_id, body, key.name), "Approval"))
