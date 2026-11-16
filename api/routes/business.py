"""Business workspace: summary and hints, the profile and its interview, the partner chat, organized documents, notes.

Every route works in the calling key's own workspace (`api.deps.business_owner`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import BusinessDep, ClientDep, JobsDep, PipelineDep, RateLimit, business_owner, require_api_key
from api.errors import responses
from business.schema import (
    AnswerRequest,
    BusinessProfile,
    HintsRequest,
    HintsResponse,
    InterviewState,
    Note,
    NoteCreate,
    OrganizedDocument,
    OrganizeRequest,
    PartnerRequest,
    PartnerResponse,
    WorkspaceSummary,
)
from core.schema import Envelope

router = APIRouter(tags=["Business"], dependencies=[Depends(require_api_key)], responses=responses(401))


@router.get("/v1/workspace", response_model=Envelope[WorkspaceSummary])
def workspace(key: ClientDep, business: BusinessDep) -> Envelope[WorkspaceSummary]:
    """Where the workspace stands: profile and interview progress, documents, assistants, connectors, approvals,
    and store listings for tools the business uses that are not connected yet."""
    return Envelope(data=business.summary(business_owner(key)))


@router.post("/v1/workspace/hints", response_model=Envelope[HintsResponse])
def hints(body: HintsRequest, key: ClientDep, business: BusinessDep) -> Envelope[HintsResponse]:
    """Contextual suggestions for the screen in `state`, given the recent `events` and the workspace."""
    return Envelope(data=business.hints(business_owner(key), body))


@router.get("/v1/business/profile", response_model=Envelope[BusinessProfile])
def get_profile(key: ClientDep, business: BusinessDep) -> Envelope[BusinessProfile]:
    return Envelope(data=business.profile(business_owner(key)))


@router.put("/v1/business/profile", response_model=Envelope[BusinessProfile], responses=responses(422))
def put_profile(body: BusinessProfile, key: ClientDep, business: BusinessDep) -> Envelope[BusinessProfile]:
    """Replace the profile (the owner's edits). `updated_at` is set by the server."""
    return Envelope(data=business.save_profile(business_owner(key), body))


@router.get("/v1/business/interview", response_model=Envelope[InterviewState])
def get_interview(key: ClientDep, business: BusinessDep) -> Envelope[InterviewState]:
    """Progress per area of the question bank and the next questions to ask."""
    return Envelope(data=business.interview(business_owner(key)))


@router.post("/v1/business/interview/answers", response_model=Envelope[InterviewState], responses=responses(404, 422))
def answer(body: AnswerRequest, key: ClientDep, business: BusinessDep) -> Envelope[InterviewState]:
    """Record (or replace) the answer to one question."""
    try:
        return Envelope(data=business.answer(business_owner(key), body))
    except KeyError:
        raise HTTPException(404, f"No question {body.question_id!r}.") from None


@router.post("/v1/partner/chat", response_model=Envelope[PartnerResponse], responses=responses(422, 429, 503),
             dependencies=[Depends(RateLimit("assistant"))])
async def partner_chat(body: PartnerRequest, key: ClientDep, business: BusinessDep, pipeline: PipelineDep,
                       jobs: JobsDep) -> Envelope[PartnerResponse]:
    """
    Talk to the business partner. Stateless: send the conversation so far, ending with the owner's message, and
    the screen it was sent from. The partner interviews the owner from the question bank, records answers and
    profile facts, organizes uploaded documents, recommends connectors and drafts assistants (JSON specs the
    owner activates).
    """
    return Envelope(data=await business.partner_chat(business_owner(key), body, pipeline=pipeline, jobs=jobs))


@router.get("/v1/business/documents", response_model=Envelope[list[OrganizedDocument]])
def documents(key: ClientDep, business: BusinessDep) -> Envelope[list[OrganizedDocument]]:
    """Library documents placed in the profile (department, kind, summary)."""
    return Envelope(data=business.documents(business_owner(key)))


@router.put("/v1/business/documents/{document_id}", response_model=Envelope[OrganizedDocument],
            responses=responses(404, 422))
def organize(document_id: str, body: OrganizeRequest, key: ClientDep,
             business: BusinessDep) -> Envelope[OrganizedDocument]:
    """Place a library document in the profile, or move it."""
    placed = business.organize(business_owner(key), document_id, body)
    if placed is None:
        raise HTTPException(404, "Document not found.")
    return Envelope(data=placed)


@router.get("/v1/business/notes", response_model=Envelope[list[Note]])
def notes(key: ClientDep, business: BusinessDep,
          topic: str | None = Query(None, description="One topic; all topics when omitted.")) -> Envelope[list[Note]]:
    """The shared notes board: facts, hand-offs and reports the assistants post per topic, newest first."""
    return Envelope(data=business.notes(business_owner(key), topic))


@router.post("/v1/business/notes", response_model=Envelope[Note], status_code=201, responses=responses(422))
def post_note(body: NoteCreate, key: ClientDep, business: BusinessDep) -> Envelope[Note]:
    """Post a note as the owner; assistants sharing the topic read it."""
    return Envelope(data=business.post_note(business_owner(key), body))
