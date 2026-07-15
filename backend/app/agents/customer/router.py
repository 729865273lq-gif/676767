from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.customer.agent import CustomerDiscoveryService
from app.agents.customer.models import CustomerDiscoveryInput, CustomerDiscoveryOutput
from app.connectors.search.bocha import BochaSearchConnector
from app.crm.models import Lead, LeadBucket, LeadEvidence
from app.crm.service import LeadService
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
    reasons: list[str]
    missing_signals: list[str]
    evidence: list[LeadEvidenceResponse]


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
