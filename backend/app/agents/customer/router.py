from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.customer.agent import CustomerDiscoveryService
from app.agents.customer.models import CustomerDiscoveryInput, CustomerDiscoveryOutput
from app.connectors.search.bocha import BochaSearchConnector
from app.crm.models import (
    CRMContact,
    EmailDraft,
    EmailDraftStatus,
    FollowUpRecord,
    Lead,
    LeadBucket,
    LeadEvidence,
    LeadStatus,
)
from app.crm.service import LeadService
from app.platform.product_lines import ProductLineNotFound, ProductLineService
from app.platform.router import current_principal, get_session
from app.platform.service import OrganizationService
from app.shared.security import SignedPrincipal
from app.workflow.models import WorkflowState

router = APIRouter(prefix="/discovery", tags=["discovery"])


class StartDiscoveryRequest(CustomerDiscoveryInput):
    idempotency_key: str = Field(min_length=1, max_length=200)


class StartDiscoveryResponse(CustomerDiscoveryOutput):
    state: str


class LeadEvidenceResponse(BaseModel):
    source_url: str
    source_excerpt: str
    signal_name: str


class LeadResponse(BaseModel):
    id: str
    workflow_run_id: str
    product_line_id: str
    company_name: str
    website: str
    target_market: str
    buyer_profile: str | None
    score: int
    bucket: LeadBucket
    status: LeadStatus
    owner_user_id: str | None
    notes: str
    reasons: list[str]
    missing_signals: list[str]
    evidence: list[LeadEvidenceResponse]


class ManualLeadRequest(BaseModel):
    product_line_id: str = Field(min_length=1, max_length=36)
    company_name: str = Field(min_length=1, max_length=300)
    website: str = Field(min_length=1, max_length=1_000)
    target_market: str = Field(min_length=1, max_length=120)
    buyer_profile: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=4_000)


class UpdateLeadRequest(BaseModel):
    status: LeadStatus
    notes: str = Field(default="", max_length=4_000)
    owner_user_id: str | None = Field(default=None, max_length=36)


class FollowUpRequest(BaseModel):
    activity_type: str = Field(default="note", min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=4_000)
    next_follow_up_at: datetime | None = None


class FollowUpResponse(BaseModel):
    id: str
    lead_id: str
    actor_user_id: str | None
    activity_type: str
    content: str
    next_follow_up_at: datetime | None
    created_at: datetime


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=80)
    linkedin_url: str = Field(default="", max_length=1_000)
    whatsapp: str = Field(default="", max_length=80)
    is_primary: bool = False


class ContactResponse(BaseModel):
    id: str
    lead_id: str
    name: str
    title: str
    email: str
    phone: str
    linkedin_url: str
    whatsapp: str
    is_primary: bool
    created_at: datetime


class CreateEmailDraftRequest(BaseModel):
    contact_id: str = Field(min_length=1, max_length=36)


class UpdateEmailDraftRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8_000)


class ReviewEmailDraftRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    rejection_reason: str = Field(default="", max_length=1_000)


class EmailDraftResponse(BaseModel):
    id: str
    organization_id: str
    lead_id: str
    contact_id: str
    product_line_id: str
    created_by_user_id: str | None
    reviewed_by_user_id: str | None
    status: EmailDraftStatus
    subject: str
    body: str
    evidence_snapshot: list[dict[str, str]]
    rejection_reason: str
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    lead_company_name: str
    contact_name: str
    contact_email: str


class LeadDetailResponse(LeadResponse):
    contacts: list[ContactResponse]
    follow_ups: list[FollowUpResponse]


def follow_up_response(record: FollowUpRecord) -> FollowUpResponse:
    return FollowUpResponse(
        id=record.id,
        lead_id=record.lead_id,
        actor_user_id=record.actor_user_id,
        activity_type=record.activity_type,
        content=record.content,
        next_follow_up_at=record.next_follow_up_at,
        created_at=record.created_at,
    )


def contact_response(contact: CRMContact) -> ContactResponse:
    return ContactResponse(
        id=contact.id,
        lead_id=contact.lead_id,
        name=contact.name,
        title=contact.title,
        email=contact.email,
        phone=contact.phone,
        linkedin_url=contact.linkedin_url,
        whatsapp=contact.whatsapp,
        is_primary=contact.is_primary,
        created_at=contact.created_at,
    )


def email_draft_response(draft: EmailDraft, session: Session) -> EmailDraftResponse:
    lead = session.scalar(select(Lead).where(Lead.id == draft.lead_id))
    contact = session.scalar(select(CRMContact).where(CRMContact.id == draft.contact_id))
    return EmailDraftResponse(
        id=draft.id,
        organization_id=draft.organization_id,
        lead_id=draft.lead_id,
        contact_id=draft.contact_id,
        product_line_id=draft.product_line_id,
        created_by_user_id=draft.created_by_user_id,
        reviewed_by_user_id=draft.reviewed_by_user_id,
        status=draft.status,
        subject=draft.subject,
        body=draft.body,
        evidence_snapshot=draft.evidence_snapshot,
        rejection_reason=draft.rejection_reason,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        reviewed_at=draft.reviewed_at,
        lead_company_name=lead.company_name if lead else "",
        contact_name=contact.name if contact else "",
        contact_email=contact.email if contact else "",
    )


def lead_response(lead: Lead, evidence: list[LeadEvidence]) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        workflow_run_id=lead.workflow_run_id,
        product_line_id=lead.product_line_id,
        company_name=lead.company_name,
        website=lead.website,
        target_market=lead.target_market,
        buyer_profile=lead.buyer_profile,
        score=lead.score,
        bucket=lead.bucket,
        status=lead.status,
        owner_user_id=lead.owner_user_id,
        notes=lead.notes,
        reasons=lead.reasons,
        missing_signals=lead.missing_signals,
        evidence=[
            LeadEvidenceResponse(
                source_url=item.source_url,
                source_excerpt=item.source_excerpt,
                signal_name=item.signal_name,
            )
            for item in evidence
        ],
    )


@router.post(
    "/organizations/{organization_id}/runs",
    response_model=StartDiscoveryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_discovery(
    organization_id: str,
    payload: StartDiscoveryRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> StartDiscoveryResponse:
    api_key = request.app.state.settings.bocha_api_key
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bocha search connector is not configured",
        )
    service = CustomerDiscoveryService(session, BochaSearchConnector(api_key))
    try:
        output = await service.start(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            payload=CustomerDiscoveryInput.model_validate(payload.model_dump()),
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except Exception as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="customer discovery failed") from error
    return StartDiscoveryResponse(**output.model_dump(), state=WorkflowState.COMPLETED)


@router.get("/organizations/{organization_id}/leads", response_model=list[LeadResponse])
def list_discovery_leads(
    organization_id: str,
    bucket: LeadBucket | None = None,
    workflow_run_id: str | None = None,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[LeadResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    service = LeadService(session)
    return [
        lead_response(lead, service.evidence_for_lead(lead.id))
        for lead in service.list_leads(
            organization_id=organization_id,
            bucket=bucket,
            workflow_run_id=workflow_run_id,
        )
    ]


@router.post(
    "/organizations/{organization_id}/leads",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_lead(
    organization_id: str,
    payload: ManualLeadRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> LeadResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        ProductLineService(session).get_product_line(payload.product_line_id, organization_id)
        service = LeadService(session)
        lead = service.create_manual_lead(
            organization_id=organization_id,
            product_line_id=payload.product_line_id,
            company_name=payload.company_name,
            website=payload.website,
            target_market=payload.target_market,
            buyer_profile=payload.buyer_profile,
            notes=payload.notes,
            actor_user_id=principal.user_id,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return lead_response(lead, service.evidence_for_lead(lead.id))


@router.get("/organizations/{organization_id}/leads/{lead_id}/detail", response_model=LeadDetailResponse)
def get_lead_detail(
    organization_id: str,
    lead_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> LeadDetailResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    service = LeadService(session)
    try:
        lead = service.get_lead(lead_id, organization_id)
        response = lead_response(lead, service.evidence_for_lead(lead.id)).model_dump()
        response["contacts"] = [
            contact_response(contact)
            for contact in service.contacts_for_lead(lead.id, organization_id)
        ]
        response["follow_ups"] = [
            follow_up_response(record)
            for record in service.follow_ups_for_lead(lead.id, organization_id)
        ]
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return LeadDetailResponse(**response)


@router.post(
    "/organizations/{organization_id}/leads/{lead_id}/contacts",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(
    organization_id: str,
    lead_id: str,
    payload: ContactRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ContactResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        contact = LeadService(session).add_contact(
            organization_id=organization_id,
            lead_id=lead_id,
            name=payload.name,
            title=payload.title,
            email=payload.email,
            phone=payload.phone,
            linkedin_url=payload.linkedin_url,
            whatsapp=payload.whatsapp,
            is_primary=payload.is_primary,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return contact_response(contact)


@router.delete(
    "/organizations/{organization_id}/leads/{lead_id}/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_contact(
    organization_id: str,
    lead_id: str,
    contact_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Response:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        LeadService(session).delete_contact(lead_id, contact_id, organization_id)
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/organizations/{organization_id}/leads/{lead_id}/email-drafts",
    response_model=EmailDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_email_draft(
    organization_id: str,
    lead_id: str,
    payload: CreateEmailDraftRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).create_email_draft(
            organization_id=organization_id,
            lead_id=lead_id,
            contact_id=payload.contact_id,
            actor_user_id=principal.user_id,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return email_draft_response(draft, session)


@router.get("/organizations/{organization_id}/email-drafts", response_model=list[EmailDraftResponse])
def list_email_drafts(
    organization_id: str,
    status_filter: EmailDraftStatus | None = None,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[EmailDraftResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    service = LeadService(session)
    return [
        email_draft_response(draft, session)
        for draft in service.list_email_drafts(
            organization_id=organization_id,
            status_filter=status_filter,
        )
    ]


@router.patch("/organizations/{organization_id}/email-drafts/{draft_id}", response_model=EmailDraftResponse)
def update_email_draft(
    organization_id: str,
    draft_id: str,
    payload: UpdateEmailDraftRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).update_email_draft(
            draft_id=draft_id,
            organization_id=organization_id,
            subject=payload.subject,
            body=payload.body,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return email_draft_response(draft, session)


@router.post("/organizations/{organization_id}/email-drafts/{draft_id}/review", response_model=EmailDraftResponse)
def review_email_draft(
    organization_id: str,
    draft_id: str,
    payload: ReviewEmailDraftRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).review_email_draft(
            draft_id=draft_id,
            organization_id=organization_id,
            reviewer_user_id=principal.user_id,
            action=payload.action,
            rejection_reason=payload.rejection_reason,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return email_draft_response(draft, session)


@router.patch("/organizations/{organization_id}/leads/{lead_id}", response_model=LeadResponse)
def update_lead_detail(
    organization_id: str,
    lead_id: str,
    payload: UpdateLeadRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> LeadResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        lead = LeadService(session).update_lead_detail(
            lead_id=lead_id,
            organization_id=organization_id,
            status=payload.status,
            notes=payload.notes,
            owner_user_id=payload.owner_user_id,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return lead_response(lead, LeadService(session).evidence_for_lead(lead.id))


@router.post(
    "/organizations/{organization_id}/leads/{lead_id}/follow-ups",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_follow_up(
    organization_id: str,
    lead_id: str,
    payload: FollowUpRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> FollowUpResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        record = LeadService(session).add_follow_up(
            organization_id=organization_id,
            lead_id=lead_id,
            actor_user_id=principal.user_id,
            activity_type=payload.activity_type,
            content=payload.content,
            next_follow_up_at=payload.next_follow_up_at,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return follow_up_response(record)


@router.get("/organizations/{organization_id}/leads/{lead_id}", response_model=LeadResponse)
def get_discovery_lead(
    organization_id: str,
    lead_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> LeadResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    service = LeadService(session)
    try:
        lead = service.get_lead(lead_id, organization_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return lead_response(lead, service.evidence_for_lead(lead.id))


@router.delete("/organizations/{organization_id}/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_discovery_lead(
    organization_id: str,
    lead_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> Response:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        LeadService(session).delete_lead(lead_id, organization_id)
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
