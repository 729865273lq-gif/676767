from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.customer.agent import CustomerDiscoveryService
from app.agents.customer.models import CustomerDiscoveryInput, CustomerDiscoveryOutput
from app.connectors.contact_discovery import (
    HunterContactDiscoveryConnector,
    WebsiteContactDiscoveryConnector,
    WebsiteContactDiscoveryError,
)
from app.connectors.contact_discovery.hunter import (
    HunterContactDiscoveryConfigurationError,
    HunterContactDiscoveryError,
)
from app.connectors.email import (
    EmailDeliveryConfigurationError,
    EmailDeliveryError,
    SmtpEmailConnector,
)
from app.connectors.email_verification import (
    DomainEmailVerificationConnector,
    DomainEmailVerificationError,
    ZeroBounceEmailVerificationConfigurationError,
    ZeroBounceEmailVerificationConnector,
    ZeroBounceEmailVerificationError,
)
from app.connectors.geography import (
    AdministrativeArea,
    GeoapifyAdministrativeAreaConnector,
    GeoapifyAdministrativeAreaError,
)
from app.connectors.search import (
    BochaSearchConnector,
    GooglePlacesSearchConnector,
    GeoapifySearchConnector,
    FoursquareSearchConnector,
    GoogleProgrammableSearchConnector,
    MultiSearchConnector,
    OpenStreetMapSearchConnector,
    SearchConnector,
    TomTomSearchConnector,
)
from app.crm.email_quality import QualityGateFailedError, quality_issues_list, quality_report_dict
from app.crm.models import (
    CRMContact,
    EmailDraft,
    EmailDraftStatus,
    FollowUpRecord,
    FollowUpTask,
    FollowUpTaskStatus,
    Lead,
    LeadBucket,
    LeadEvidence,
    LeadStatus,
    QuoteDraft,
    QuoteDraftStatus,
    WebsiteInquiry,
    WebsiteInquiryStatus,
)
from app.crm.service import BLOCKED_EMAIL_VERIFICATION_STATUSES, LeadService, normalized_email_verification_status, quote_total
from app.platform.product_lines import ProductItemNotFound, ProductLineNotFound, ProductLineService
from app.platform.models import SearchSourcePreference
from app.platform.router import current_principal, get_session
from app.platform.search_keywords import build_search_keyword_provider
from app.platform.service import OrganizationService
from app.shared.security import SignedPrincipal
from app.workflow.models import WorkflowRun, WorkflowState

router = APIRouter(prefix="/discovery", tags=["discovery"])


class StartDiscoveryRequest(CustomerDiscoveryInput):
    idempotency_key: str = Field(min_length=1, max_length=200)


class StartDiscoveryResponse(CustomerDiscoveryOutput):
    state: str


class ResolveLocationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    product_line_id: str = Field(default="", max_length=36)


class AdministrativeAreaResponse(BaseModel):
    scope_id: str
    name: str
    formatted: str
    search_label: str
    country_code: str
    level: str
    search_count: int
    last_searched_at: datetime | None


class ResolveLocationResponse(BaseModel):
    area: AdministrativeAreaResponse
    subdivisions: list[AdministrativeAreaResponse]


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
    contact_discovery_status: str
    contact_discovery_message: str
    contact_discovered_at: datetime | None
    contact_email_count: int
    contact_phone_count: int
    contact_social_count: int
    last_discovered_at: datetime
    created_at: datetime
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


class OrganizationFollowUpResponse(FollowUpResponse):
    lead_company_name: str
    lead_status: LeadStatus


class FollowUpTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    task_type: str = Field(default="follow_up", min_length=1, max_length=50)
    quote_status: str = Field(default="", max_length=50)
    due_at: datetime | None = None


class FollowUpTaskResponse(BaseModel):
    id: str
    lead_id: str
    actor_user_id: str | None
    title: str
    task_type: str
    quote_status: str
    due_at: datetime | None
    status: FollowUpTaskStatus
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrganizationFollowUpTaskResponse(FollowUpTaskResponse):
    lead_company_name: str
    lead_status: LeadStatus


class QuoteLineItemRequest(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    unit: str = Field(default="pcs", max_length=50)
    notes: str = Field(default="", max_length=500)


class QuoteLineItemResponse(BaseModel):
    item_name: str
    quantity: float
    unit_price: float
    unit: str
    notes: str


class QuoteDraftRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="USD", min_length=1, max_length=10)
    incoterm: str = Field(default="FOB", min_length=1, max_length=20)
    valid_until: datetime | None = None
    line_items: list[QuoteLineItemRequest] = Field(min_length=1, max_length=20)
    notes: str = Field(default="", max_length=2_000)


class QuoteDraftResponse(BaseModel):
    id: str
    organization_id: str
    lead_id: str
    product_line_id: str
    created_by_user_id: str | None
    sent_by_user_id: str | None
    status: QuoteDraftStatus
    title: str
    currency: str
    incoterm: str
    valid_until: datetime | None
    line_items: list[QuoteLineItemResponse]
    notes: str
    total_amount: float
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    lead_company_name: str


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=80)
    linkedin_url: str = Field(default="", max_length=1_000)
    whatsapp: str = Field(default="", max_length=80)
    social_profiles: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    source_url: str = Field(default="", max_length=1_000)
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
    social_profiles: list[dict[str, str]]
    source_url: str
    email_verification_provider: str
    email_verification_status: str
    email_verification_sub_status: str
    email_verified_at: datetime | None
    is_primary: bool
    created_at: datetime


class DiscoverContactsRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=25)


class BatchContactDiscoveryRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=5)
    contacts_per_lead: int = Field(default=10, ge=1, le=25)


class BatchContactDiscoveryItemResponse(BaseModel):
    lead_id: str
    company_name: str
    website: str
    status: str
    contact_count: int
    email_count: int
    checked_email_count: int
    phone_count: int
    social_count: int
    message: str


class BatchContactDiscoveryResponse(BaseModel):
    items: list[BatchContactDiscoveryItemResponse]


class DailyContactDiscoveryRequest(BaseModel):
    discovery_date: date | None = None
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    lead_limit: int = Field(default=50, ge=1, le=50)
    contacts_per_lead: int = Field(default=10, ge=1, le=25)


class DailyContactDiscoveryItemResponse(BaseModel):
    lead_id: str
    company_name: str
    website: str
    status: str
    contact_count: int
    message: str


class DailyContactDiscoveryResponse(BaseModel):
    discovery_date: date
    timezone: str
    lead_count: int
    processed_count: int
    contacts_found: int
    no_contacts_count: int
    skipped_count: int
    failed_count: int
    items: list[DailyContactDiscoveryItemResponse]


class CreateEmailDraftRequest(BaseModel):
    contact_id: str = Field(min_length=1, max_length=36)


class UpdateEmailDraftRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8_000)


class UpdateDraftContactEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ReviewEmailDraftRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    rejection_reason: str = Field(default="", max_length=1_000)


class QualityIssueResponse(BaseModel):
    code: str
    message: str
    suggestion: str


class QualityReportResponse(BaseModel):
    passed: bool
    issues: list[QualityIssueResponse]
    product_evidence: list[str]
    customer_evidence: list[str]


class EmailDraftResponse(BaseModel):
    id: str
    organization_id: str
    lead_id: str
    contact_id: str
    product_line_id: str
    created_by_user_id: str | None
    reviewed_by_user_id: str | None
    sent_by_user_id: str | None
    status: EmailDraftStatus
    subject: str
    body: str
    provider_message_id: str
    evidence_snapshot: list[dict[str, str]]
    rejection_reason: str
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    sent_at: datetime | None
    lead_company_name: str
    contact_name: str
    contact_email: str
    current_contact_email: str
    contact_email_verification_provider: str
    contact_email_verification_status: str
    contact_email_verification_sub_status: str
    contact_email_verified_at: datetime | None
    contact_source_url: str
    send_blocked: bool
    send_risk_level: str
    send_risk_message: str
    quality: QualityReportResponse | None


class LeadDetailResponse(LeadResponse):
    contacts: list[ContactResponse]
    follow_ups: list[FollowUpResponse]
    follow_up_tasks: list[FollowUpTaskResponse]
    quote_drafts: list[QuoteDraftResponse]


class WebsiteInquiryRequest(BaseModel):
    product_line_id: str = Field(min_length=1, max_length=36)
    product_item_id: str | None = Field(default=None, max_length=36)
    company_name: str = Field(min_length=1, max_length=300)
    contact_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=80)
    website: str = Field(default="", max_length=1_000)
    target_market: str = Field(default="", max_length=120)
    message: str = Field(min_length=1, max_length=4_000)
    source_url: str = Field(default="", max_length=1_000)


class WebsiteInquiryResponse(BaseModel):
    id: str
    organization_id: str
    product_line_id: str | None
    product_item_id: str | None
    lead_id: str | None
    status: WebsiteInquiryStatus
    company_name: str
    contact_name: str
    email: str
    phone: str
    website: str
    target_market: str
    message: str
    source_url: str
    product_item_name: str
    created_at: datetime
    converted_at: datetime | None


class WebsiteInquiryConversionResponse(BaseModel):
    inquiry: WebsiteInquiryResponse
    lead: LeadDetailResponse


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


def organization_follow_up_response(record: FollowUpRecord, lead: Lead) -> OrganizationFollowUpResponse:
    return OrganizationFollowUpResponse(
        **follow_up_response(record).model_dump(),
        lead_company_name=lead.company_name,
        lead_status=lead.status,
    )


def follow_up_task_response(task: FollowUpTask) -> FollowUpTaskResponse:
    return FollowUpTaskResponse(
        id=task.id,
        lead_id=task.lead_id,
        actor_user_id=task.actor_user_id,
        title=task.title,
        task_type=task.task_type,
        quote_status=task.quote_status,
        due_at=task.due_at,
        status=task.status,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def organization_follow_up_task_response(task: FollowUpTask, lead: Lead) -> OrganizationFollowUpTaskResponse:
    return OrganizationFollowUpTaskResponse(
        **follow_up_task_response(task).model_dump(),
        lead_company_name=lead.company_name,
        lead_status=lead.status,
    )


def quote_draft_response(draft: QuoteDraft, session: Session) -> QuoteDraftResponse:
    lead = session.scalar(select(Lead).where(Lead.id == draft.lead_id))
    return QuoteDraftResponse(
        id=draft.id,
        organization_id=draft.organization_id,
        lead_id=draft.lead_id,
        product_line_id=draft.product_line_id,
        created_by_user_id=draft.created_by_user_id,
        sent_by_user_id=draft.sent_by_user_id,
        status=draft.status,
        title=draft.title,
        currency=draft.currency,
        incoterm=draft.incoterm,
        valid_until=draft.valid_until,
        line_items=[QuoteLineItemResponse(**item) for item in draft.line_items],
        notes=draft.notes,
        total_amount=quote_total(draft.line_items),
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        sent_at=draft.sent_at,
        lead_company_name=lead.company_name if lead else "",
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
        social_profiles=contact.social_profiles,
        source_url=contact.source_url,
        email_verification_provider=contact.email_verification_provider,
        email_verification_status=contact.email_verification_status,
        email_verification_sub_status=contact.email_verification_sub_status,
        email_verified_at=contact.email_verified_at,
        is_primary=contact.is_primary,
        created_at=contact.created_at,
    )


def email_draft_send_assessment(contact: CRMContact | None) -> dict[str, str | bool]:
    if contact is None:
        return {
            "blocked": True,
            "level": "blocked",
            "message": "联系人不存在，不能发送开发信。",
        }
    status = normalized_email_verification_status(contact)
    if status in BLOCKED_EMAIL_VERIFICATION_STATUSES:
        return {
            "blocked": True,
            "level": "blocked",
            "message": f"邮箱验证结果为 {contact.email_verification_status}，已阻止发送。",
        }
    if status == "valid":
        return {
            "blocked": False,
            "level": "safe",
            "message": f"邮箱已通过 {contact.email_verification_provider or '验证服务'} 验证，可以发送。",
        }
    if status in {"catch_all", "accept_all", "unknown"}:
        return {
            "blocked": False,
            "level": "caution",
            "message": f"邮箱验证结果为 {contact.email_verification_status}，建议人工确认后再发送。",
        }
    if status == "domain_reachable":
        return {
            "blocked": False,
            "level": "caution",
            "message": "邮箱格式和域名基础检查正常，但尚未验证具体邮箱是否可投递，请人工确认。",
        }
    if status == "domain_unreachable":
        return {
            "blocked": True,
            "level": "blocked",
            "message": "邮箱域名无法解析，建议修改邮箱后重新验证。",
        }
    return {
        "blocked": False,
        "level": "warning",
        "message": "邮箱尚未验证，建议先在客户详情里验证邮箱再发送。",
    }


def email_draft_response(draft: EmailDraft, session: Session, *, include_quality: bool = True) -> EmailDraftResponse:
    lead = session.scalar(select(Lead).where(Lead.id == draft.lead_id))
    contact = session.scalar(select(CRMContact).where(CRMContact.id == draft.contact_id))
    send_assessment = email_draft_send_assessment(contact)
    quality = (
        quality_report_dict(LeadService(session).evaluate_email_draft_quality(draft))
        if include_quality
        else None
    )
    return EmailDraftResponse(
        id=draft.id,
        organization_id=draft.organization_id,
        lead_id=draft.lead_id,
        contact_id=draft.contact_id,
        product_line_id=draft.product_line_id,
        created_by_user_id=draft.created_by_user_id,
        reviewed_by_user_id=draft.reviewed_by_user_id,
        sent_by_user_id=draft.sent_by_user_id,
        status=draft.status,
        subject=draft.subject,
        body=draft.body,
        provider_message_id=draft.provider_message_id,
        evidence_snapshot=draft.evidence_snapshot,
        rejection_reason=draft.rejection_reason,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        reviewed_at=draft.reviewed_at,
        sent_at=draft.sent_at,
        lead_company_name=lead.company_name if lead else "",
        contact_name=contact.name if contact else "",
        contact_email=(draft.recipient_email or (contact.email if contact else "")),
        current_contact_email=contact.email if contact else "",
        contact_email_verification_provider=contact.email_verification_provider if contact else "",
        contact_email_verification_status=contact.email_verification_status if contact else "",
        contact_email_verification_sub_status=contact.email_verification_sub_status if contact else "",
        contact_email_verified_at=contact.email_verified_at if contact else None,
        contact_source_url=contact.source_url if contact else "",
        send_blocked=bool(send_assessment["blocked"]),
        send_risk_level=str(send_assessment["level"]),
        send_risk_message=str(send_assessment["message"]),
        quality=quality,
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
        contact_discovery_status=lead.contact_discovery_status,
        contact_discovery_message=lead.contact_discovery_message,
        contact_discovered_at=lead.contact_discovered_at,
        contact_email_count=lead.contact_email_count,
        contact_phone_count=lead.contact_phone_count,
        contact_social_count=lead.contact_social_count,
        last_discovered_at=lead.last_discovered_at,
        created_at=lead.created_at,
        evidence=[
            LeadEvidenceResponse(
                source_url=item.source_url,
                source_excerpt=item.source_excerpt,
                signal_name=item.signal_name,
            )
            for item in evidence
        ],
    )


def lead_detail_response(lead: Lead, service: LeadService, organization_id: str) -> LeadDetailResponse:
    response = lead_response(lead, service.evidence_for_lead(lead.id)).model_dump()
    response["contacts"] = [
        contact_response(contact)
        for contact in service.contacts_for_lead(lead.id, organization_id)
    ]
    response["follow_ups"] = [
        follow_up_response(record)
        for record in service.follow_ups_for_lead(lead.id, organization_id)
    ]
    response["follow_up_tasks"] = [
        follow_up_task_response(task)
        for task in service.follow_up_tasks_for_lead(lead.id, organization_id)
    ]
    response["quote_drafts"] = [
        quote_draft_response(draft, service.session)
        for draft in service.quote_drafts_for_lead(lead.id, organization_id)
    ]
    return LeadDetailResponse(**response)


def website_inquiry_response(inquiry: WebsiteInquiry) -> WebsiteInquiryResponse:
    return WebsiteInquiryResponse(
        id=inquiry.id,
        organization_id=inquiry.organization_id,
        product_line_id=inquiry.product_line_id,
        product_item_id=inquiry.product_item_id,
        lead_id=inquiry.lead_id,
        status=inquiry.status,
        company_name=inquiry.company_name,
        contact_name=inquiry.contact_name,
        email=inquiry.email,
        phone=inquiry.phone,
        website=inquiry.website,
        target_market=inquiry.target_market,
        message=inquiry.message,
        source_url=inquiry.source_url,
        product_item_name=inquiry.product_item_name,
        created_at=inquiry.created_at,
        converted_at=inquiry.converted_at,
    )


def build_customer_search_connector(
    organization_id: str,
    request: Request,
    session: Session,
    payload: CustomerDiscoveryInput | None = None,
) -> SearchConnector:
    injected_connector = getattr(request.app.state, "search_connector", None)
    if injected_connector is not None:
        return injected_connector

    settings = request.app.state.settings
    preferences = {
        preference.source_id: preference.enabled
        for preference in session.scalars(
            select(SearchSourcePreference).where(SearchSourcePreference.organization_id == organization_id)
        )
    }

    def enabled(source_id: str, default: bool) -> bool:
        return preferences.get(source_id, default)

    connectors: list[SearchConnector] = []
    if enabled("tomtom", True) and settings.tomtom_api_key:
        connectors.append(TomTomSearchConnector(settings.tomtom_api_key))
    if enabled("geoapify", True) and settings.geoapify_api_key:
        connectors.append(
            GeoapifySearchConnector(
                settings.geoapify_api_key,
                target_market=payload.target_market if payload else "",
            )
        )
    if enabled("foursquare", True) and settings.foursquare_api_key:
        connectors.append(
            FoursquareSearchConnector(
                settings.foursquare_api_key,
                target_market=payload.target_market if payload else "",
            )
        )
    if enabled("bocha", True) and settings.bocha_api_key:
        connectors.append(BochaSearchConnector(settings.bocha_api_key))
    if enabled("openstreetmap", True):
        connectors.append(
            OpenStreetMapSearchConnector(target_market=payload.target_market if payload else "")
        )
    if enabled("google_cse", False) and settings.google_cse_api_key and settings.google_cse_cx:
        connectors.append(GoogleProgrammableSearchConnector(settings.google_cse_api_key, settings.google_cse_cx))
    if enabled("google_places", False) and settings.google_places_api_key:
        connectors.append(GooglePlacesSearchConnector(settings.google_places_api_key))

    if not connectors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No enabled customer search connector is configured",
        )
    if len(connectors) == 1:
        return connectors[0]
    return MultiSearchConnector(connectors)


@router.post(
    "/public/organizations/{organization_id}/website-inquiries",
    response_model=WebsiteInquiryResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_website_inquiry(
    organization_id: str,
    payload: WebsiteInquiryRequest,
    session: Session = Depends(get_session),
) -> WebsiteInquiryResponse:
    try:
        product_service = ProductLineService(session)
        product_service.get_product_line(payload.product_line_id, organization_id)
        product_item_name = ""
        if payload.product_item_id:
            product_item = product_service.get_product_item(
                payload.product_item_id,
                organization_id,
                product_line_id=payload.product_line_id,
            )
            product_item_name = product_item.name
        inquiry = LeadService(session).create_website_inquiry(
            organization_id=organization_id,
            product_line_id=payload.product_line_id,
            product_item_id=payload.product_item_id,
            product_item_name=product_item_name,
            company_name=payload.company_name,
            contact_name=payload.contact_name,
            email=payload.email,
            phone=payload.phone,
            website=payload.website,
            target_market=payload.target_market,
            message=payload.message,
            source_url=payload.source_url,
        )
        session.commit()
    except ProductLineNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ProductItemNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return website_inquiry_response(inquiry)


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
    discovery_payload = CustomerDiscoveryInput.model_validate(payload.model_dump())
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        if discovery_payload.location_scope_id and not discovery_payload.allow_repeat_location:
            previous_search = location_search_coverage(
                session,
                organization_id=organization_id,
                product_line_id=discovery_payload.product_line_id,
            ).get(discovery_payload.location_scope_id)
            if previous_search is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="这个产品线已经搜索过该行政区；如需更新结果，请勾选允许重新搜索",
                )
        service = CustomerDiscoveryService(
            session,
            build_customer_search_connector(organization_id, request, session, discovery_payload),
            keyword_provider=build_search_keyword_provider(
                getattr(request.app.state, "llm_connector", None)
            ),
        )
        output = await service.start(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            payload=discovery_payload,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except HTTPException:
        session.rollback()
        raise
    except Exception as error:
        session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="customer discovery failed") from error
    return StartDiscoveryResponse(**output.model_dump(), state=WorkflowState.COMPLETED)


@router.post(
    "/organizations/{organization_id}/locations/resolve",
    response_model=ResolveLocationResponse,
)
async def resolve_search_location(
    organization_id: str,
    payload: ResolveLocationRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ResolveLocationResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        if payload.product_line_id:
            ProductLineService(session).get_product_line(payload.product_line_id, organization_id)
        connector = getattr(request.app.state, "administrative_area_connector", None)
        if connector is None:
            api_key = request.app.state.settings.geoapify_api_key
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="需要先配置 Geoapify API，才能自动识别全球行政区",
                )
            connector = GeoapifyAdministrativeAreaConnector(api_key)
        area = await connector.resolve(payload.query)
        subdivisions = await connector.subdivisions(area)
        coverage = location_search_coverage(
            session,
            organization_id=organization_id,
            product_line_id=payload.product_line_id,
        )
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (GeoapifyAdministrativeAreaError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return ResolveLocationResponse(
        area=administrative_area_response(area, coverage),
        subdivisions=[administrative_area_response(child, coverage) for child in subdivisions],
    )


def location_search_coverage(
    session: Session,
    *,
    organization_id: str,
    product_line_id: str,
) -> dict[str, tuple[int, datetime]]:
    runs = session.scalars(
        select(WorkflowRun)
        .where(
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.agent_id == "customer",
            WorkflowRun.state == WorkflowState.COMPLETED,
        )
        .order_by(WorkflowRun.created_at.desc())
    )
    coverage: dict[str, tuple[int, datetime]] = {}
    for run in runs:
        inputs = run.input_json if isinstance(run.input_json, dict) else {}
        scope_id = str(inputs.get("location_scope_id", "")).strip()
        if not scope_id or (product_line_id and inputs.get("product_line_id") != product_line_id):
            continue
        count, last_searched_at = coverage.get(scope_id, (0, run.created_at))
        coverage[scope_id] = (count + 1, max(last_searched_at, run.created_at))
    return coverage


def administrative_area_response(
    area: AdministrativeArea,
    coverage: dict[str, tuple[int, datetime]],
) -> AdministrativeAreaResponse:
    search_count, last_searched_at = coverage.get(area.scope_id, (0, None))
    return AdministrativeAreaResponse(
        scope_id=area.scope_id,
        name=area.name,
        formatted=area.formatted,
        search_label=area.search_label[:120],
        country_code=area.country_code,
        level=area.level,
        search_count=search_count,
        last_searched_at=last_searched_at,
    )


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
            product_item_id=None,
            product_item_name="",
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
        response = lead_detail_response(lead, service, organization_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return response


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
            social_profiles=payload.social_profiles,
            source_url=payload.source_url,
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
    "/organizations/{organization_id}/leads/{lead_id}/contacts/{contact_id}/verify-email",
    response_model=ContactResponse,
)
def verify_contact_email(
    organization_id: str,
    lead_id: str,
    contact_id: str,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ContactResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        service = LeadService(session)
        contact = service.get_contact(contact_id, lead_id, organization_id)
        if not contact.email:
            raise ValueError("contact email is required")
        connector = getattr(request.app.state, "email_verification_connector", None)
        if connector is None:
            if request.app.state.settings.zerobounce_api_key:
                connector = ZeroBounceEmailVerificationConnector(
                    request.app.state.settings.zerobounce_api_key
                )
            else:
                connector = DomainEmailVerificationConnector()
        result = connector.verify(contact.email)
        verified_contact = service.verify_contact_email(
            organization_id=organization_id,
            lead_id=lead_id,
            contact_id=contact_id,
            actor_user_id=principal.user_id,
            result=result,
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
    except ZeroBounceEmailVerificationConfigurationError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ZeroBounceEmailVerificationError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except DomainEmailVerificationError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return contact_response(verified_contact)


@router.post(
    "/organizations/{organization_id}/leads/{lead_id}/contacts/discover",
    response_model=list[ContactResponse],
    status_code=status.HTTP_201_CREATED,
)
def discover_contacts(
    organization_id: str,
    lead_id: str,
    payload: DiscoverContactsRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ContactResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        service = LeadService(session)
        lead = service.get_lead(lead_id, organization_id)
        connector = getattr(request.app.state, "contact_discovery_connector", None)
        if connector is not None:
            discovered = connector.discover(lead.canonical_domain, payload.limit)
        else:
            discovered = []
            provider_errors: list[Exception] = []
            has_business_website = not lead.canonical_domain.startswith(("osm:", "google-place:"))
            if has_business_website:
                try:
                    discovered.extend(
                        WebsiteContactDiscoveryConnector().discover(lead.website, payload.limit)
                    )
                except WebsiteContactDiscoveryError as error:
                    provider_errors.append(error)
                if request.app.state.settings.hunter_api_key:
                    try:
                        discovered.extend(
                            HunterContactDiscoveryConnector(
                                request.app.state.settings.hunter_api_key
                            ).discover(lead.canonical_domain, payload.limit)
                        )
                    except HunterContactDiscoveryError as error:
                        provider_errors.append(error)
            if not discovered and provider_errors:
                raise WebsiteContactDiscoveryError("public contact discovery failed")
        contacts = service.add_discovered_contacts(
            organization_id=organization_id,
            lead_id=lead_id,
            actor_user_id=principal.user_id,
            discovered_contacts=discovered,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except HunterContactDiscoveryConfigurationError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except HunterContactDiscoveryError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except WebsiteContactDiscoveryError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return [contact_response(contact) for contact in contacts]


@router.post(
    "/organizations/{organization_id}/contacts/discover-batch",
    response_model=BatchContactDiscoveryResponse,
)
def discover_contact_batch(
    organization_id: str,
    payload: BatchContactDiscoveryRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> BatchContactDiscoveryResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        service = LeadService(session)
        connector = getattr(request.app.state, "contact_discovery_connector", None)
        items: list[BatchContactDiscoveryItemResponse] = []
        for lead_id in dict.fromkeys(payload.lead_ids):
            lead = service.get_lead(lead_id, organization_id)
            has_business_website = not lead.canonical_domain.startswith(
                ("osm:", "google-place:", "tomtom-place:", "geoapify-place:", "foursquare-place:")
            )
            if not has_business_website:
                refreshed = service.refresh_lead_contact_summary(
                    lead.id,
                    organization_id,
                    scan_status="needs_review",
                    message="没有企业官网，请使用电话或社交媒体人工联系",
                    scanned=True,
                )
                session.commit()
                items.append(batch_contact_discovery_item(refreshed, 0, 0))
                continue
            try:
                discovered = []
                if connector is not None:
                    discovered.extend(
                        connector.discover(lead.canonical_domain, payload.contacts_per_lead)
                    )
                else:
                    discovered.extend(
                        WebsiteContactDiscoveryConnector().discover(
                            lead.website, payload.contacts_per_lead
                        )
                    )
                    if request.app.state.settings.hunter_api_key:
                        discovered.extend(
                            HunterContactDiscoveryConnector(
                                request.app.state.settings.hunter_api_key
                            ).discover(lead.canonical_domain, payload.contacts_per_lead)
                        )
                changed = service.add_discovered_contacts(
                    organization_id=organization_id,
                    lead_id=lead.id,
                    actor_user_id=principal.user_id,
                    discovered_contacts=discovered,
                )
                checked_email_count = check_discovered_contact_emails(
                    request=request,
                    service=service,
                    contacts=changed,
                    organization_id=organization_id,
                    lead_id=lead.id,
                    actor_user_id=principal.user_id,
                )
                message = (
                    f"新增或更新 {len(changed)} 条公开联系方式"
                    if changed
                    else "官网未发现新的公开联系方式"
                )
                refreshed = service.refresh_lead_contact_summary(
                    lead.id,
                    organization_id,
                    scan_status="no_contacts",
                    message=message,
                    scanned=True,
                )
                session.commit()
                items.append(
                    batch_contact_discovery_item(
                        refreshed,
                        len(changed),
                        checked_email_count,
                    )
                )
            except (
                HunterContactDiscoveryConfigurationError,
                HunterContactDiscoveryError,
                WebsiteContactDiscoveryError,
                ValueError,
            ):
                session.rollback()
                refreshed = LeadService(session).refresh_lead_contact_summary(
                    lead_id,
                    organization_id,
                    scan_status="needs_review",
                    message="官网访问或联系方式提取失败，可稍后重试",
                    scanned=True,
                )
                session.commit()
                items.append(batch_contact_discovery_item(refreshed, 0, 0))
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return BatchContactDiscoveryResponse(items=items)


def batch_contact_discovery_item(
    lead: Lead, contact_count: int, checked_email_count: int
) -> BatchContactDiscoveryItemResponse:
    return BatchContactDiscoveryItemResponse(
        lead_id=lead.id,
        company_name=lead.company_name,
        website=lead.website,
        status=lead.contact_discovery_status,
        contact_count=contact_count,
        email_count=lead.contact_email_count,
        checked_email_count=checked_email_count,
        phone_count=lead.contact_phone_count,
        social_count=lead.contact_social_count,
        message=lead.contact_discovery_message,
    )


def check_discovered_contact_emails(
    *,
    request: Request,
    service: LeadService,
    contacts: list[CRMContact],
    organization_id: str,
    lead_id: str,
    actor_user_id: str,
) -> int:
    connector = getattr(request.app.state, "email_verification_connector", None)
    if connector is None:
        connector = DomainEmailVerificationConnector()
    checked_count = 0
    for contact in contacts:
        if not contact.email or contact.email_verified_at is not None:
            continue
        try:
            result = connector.verify(contact.email)
            service.verify_contact_email(
                organization_id=organization_id,
                lead_id=lead_id,
                contact_id=contact.id,
                actor_user_id=actor_user_id,
                result=result,
            )
            checked_count += 1
        except (
            DomainEmailVerificationError,
            ZeroBounceEmailVerificationConfigurationError,
            ZeroBounceEmailVerificationError,
            ValueError,
        ):
            continue
    return checked_count


@router.post(
    "/organizations/{organization_id}/contacts/discover-daily",
    response_model=DailyContactDiscoveryResponse,
)
def discover_daily_contacts(
    organization_id: str,
    payload: DailyContactDiscoveryRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> DailyContactDiscoveryResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        try:
            local_timezone = ZoneInfo(payload.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown timezone") from error

        local_date = payload.discovery_date or datetime.now(local_timezone).date()
        local_start = datetime.combine(local_date, time.min, tzinfo=local_timezone)
        local_end = local_start + timedelta(days=1)
        discovered_from = local_start.astimezone(timezone.utc)
        discovered_before = local_end.astimezone(timezone.utc)

        service = LeadService(session)
        leads = service.list_leads_discovered_between(
            organization_id=organization_id,
            discovered_from=discovered_from,
            discovered_before=discovered_before,
            limit=payload.lead_limit,
        )
        items: list[DailyContactDiscoveryItemResponse] = []
        contacts_found = 0
        no_contacts_count = 0
        skipped_count = 0
        failed_count = 0
        connector = getattr(request.app.state, "contact_discovery_connector", None)

        for lead in leads:
            has_business_website = not lead.canonical_domain.startswith(
                ("osm:", "google-place:", "tomtom-place:", "geoapify-place:", "foursquare-place:")
            )
            if not has_business_website:
                skipped_count += 1
                items.append(
                    DailyContactDiscoveryItemResponse(
                        lead_id=lead.id,
                        company_name=lead.company_name,
                        website=lead.website,
                        status="skipped",
                        contact_count=0,
                        message="没有企业官网，无法扫描公开联系方式",
                    )
                )
                continue

            try:
                discovered = []
                if connector is not None:
                    discovered.extend(connector.discover(lead.canonical_domain, payload.contacts_per_lead))
                else:
                    discovered.extend(
                        WebsiteContactDiscoveryConnector().discover(
                            lead.website,
                            payload.contacts_per_lead,
                        )
                    )
                    if request.app.state.settings.hunter_api_key:
                        discovered.extend(
                            HunterContactDiscoveryConnector(
                                request.app.state.settings.hunter_api_key
                            ).discover(lead.canonical_domain, payload.contacts_per_lead)
                        )
                contacts = service.add_discovered_contacts(
                    organization_id=organization_id,
                    lead_id=lead.id,
                    actor_user_id=principal.user_id,
                    discovered_contacts=discovered,
                )
                session.commit()
                contacts_found += len(contacts)
                if contacts:
                    status_text = "found"
                    message = f"新增或更新 {len(contacts)} 条公开联系方式"
                else:
                    status_text = "no_contacts"
                    message = "官网未发现新的公开联系方式"
                    no_contacts_count += 1
                items.append(
                    DailyContactDiscoveryItemResponse(
                        lead_id=lead.id,
                        company_name=lead.company_name,
                        website=lead.website,
                        status=status_text,
                        contact_count=len(contacts),
                        message=message,
                    )
                )
            except (
                HunterContactDiscoveryConfigurationError,
                HunterContactDiscoveryError,
                WebsiteContactDiscoveryError,
                ValueError,
            ):
                session.rollback()
                failed_count += 1
                items.append(
                    DailyContactDiscoveryItemResponse(
                        lead_id=lead.id,
                        company_name=lead.company_name,
                        website=lead.website,
                        status="failed",
                        contact_count=0,
                        message="官网访问或联系方式提取失败，可稍后重试",
                    )
                )
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    return DailyContactDiscoveryResponse(
        discovery_date=local_date,
        timezone=payload.timezone,
        lead_count=len(leads),
        processed_count=len(leads) - skipped_count,
        contacts_found=contacts_found,
        no_contacts_count=no_contacts_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        items=items,
    )


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
        email_draft_response(draft, session, include_quality=False)
        for draft in service.list_email_drafts(
            organization_id=organization_id,
            status_filter=status_filter,
        )
    ]


@router.get(
    "/organizations/{organization_id}/email-drafts/{draft_id}",
    response_model=EmailDraftResponse,
)
def get_email_draft(
    organization_id: str,
    draft_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).get_email_draft(draft_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return email_draft_response(draft, session)


@router.get(
    "/organizations/{organization_id}/website-inquiries",
    response_model=list[WebsiteInquiryResponse],
)
def list_website_inquiries(
    organization_id: str,
    status_filter: WebsiteInquiryStatus | None = None,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[WebsiteInquiryResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return [
        website_inquiry_response(inquiry)
        for inquiry in LeadService(session).list_website_inquiries(
            organization_id=organization_id,
            status_filter=status_filter,
        )
    ]


@router.post(
    "/organizations/{organization_id}/website-inquiries/{inquiry_id}/convert",
    response_model=WebsiteInquiryConversionResponse,
)
def convert_website_inquiry(
    organization_id: str,
    inquiry_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> WebsiteInquiryConversionResponse:
    service = LeadService(session)
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        inquiry, lead = service.convert_website_inquiry(
            inquiry_id=inquiry_id,
            organization_id=organization_id,
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
    return WebsiteInquiryConversionResponse(
        inquiry=website_inquiry_response(inquiry),
        lead=lead_detail_response(lead, service, organization_id),
    )


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


@router.patch(
    "/organizations/{organization_id}/email-drafts/{draft_id}/contact-email",
    response_model=EmailDraftResponse,
)
def update_draft_contact_email(
    organization_id: str,
    draft_id: str,
    payload: UpdateDraftContactEmailRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).update_draft_contact_email(
            draft_id=draft_id,
            organization_id=organization_id,
            actor_user_id=principal.user_id,
            email=payload.email,
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
    except QualityGateFailedError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=quality_issues_list(error.report),
        ) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return email_draft_response(draft, session)


@router.post("/organizations/{organization_id}/email-drafts/{draft_id}/send", response_model=EmailDraftResponse)
def mark_email_draft_sent(
    organization_id: str,
    draft_id: str,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        service = LeadService(session)
        draft = service.get_email_draft_for_update(draft_id, organization_id)
        if draft.status == EmailDraftStatus.SENT:
            return email_draft_response(draft, session)
        draft, outbound_message = service.email_draft_outbound_message(
            draft_id=draft_id,
            organization_id=organization_id,
        )
        email_connector = getattr(request.app.state, "email_connector", None)
        if email_connector is None:
            email_connector = SmtpEmailConnector.from_settings(request.app.state.settings)
        provider_message_id = email_connector.send(
            outbound_message,
            idempotency_key=f"email-draft:{draft.id}",
        )
        draft = service.mark_email_draft_sent(
            draft_id=draft_id,
            organization_id=organization_id,
            actor_user_id=principal.user_id,
            provider_message_id=provider_message_id,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except EmailDeliveryConfigurationError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except EmailDeliveryError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
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


@router.post(
    "/organizations/{organization_id}/leads/{lead_id}/follow-up-tasks",
    response_model=FollowUpTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_follow_up_task(
    organization_id: str,
    lead_id: str,
    payload: FollowUpTaskRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> FollowUpTaskResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        task = LeadService(session).create_follow_up_task(
            organization_id=organization_id,
            lead_id=lead_id,
            actor_user_id=principal.user_id,
            title=payload.title,
            task_type=payload.task_type,
            quote_status=payload.quote_status,
            due_at=payload.due_at,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return follow_up_task_response(task)


@router.get("/organizations/{organization_id}/follow-ups", response_model=list[OrganizationFollowUpResponse])
def list_follow_ups(
    organization_id: str,
    limit: int = 20,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[OrganizationFollowUpResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    safe_limit = min(max(limit, 1), 50)
    return [
        organization_follow_up_response(record, lead)
        for record, lead in LeadService(session).list_follow_ups(
            organization_id=organization_id,
            limit=safe_limit,
        )
    ]


@router.get("/organizations/{organization_id}/follow-up-tasks", response_model=list[OrganizationFollowUpTaskResponse])
def list_follow_up_tasks(
    organization_id: str,
    status_filter: FollowUpTaskStatus | None = FollowUpTaskStatus.OPEN,
    limit: int = 20,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[OrganizationFollowUpTaskResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    safe_limit = min(max(limit, 1), 50)
    return [
        organization_follow_up_task_response(task, lead)
        for task, lead in LeadService(session).list_follow_up_tasks(
            organization_id=organization_id,
            status_filter=status_filter,
            limit=safe_limit,
        )
    ]


@router.post(
    "/organizations/{organization_id}/follow-up-tasks/{task_id}/complete",
    response_model=FollowUpTaskResponse,
)
def complete_follow_up_task(
    organization_id: str,
    task_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> FollowUpTaskResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        task = LeadService(session).complete_follow_up_task(
            organization_id=organization_id,
            task_id=task_id,
            actor_user_id=principal.user_id,
        )
        session.commit()
    except PermissionError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return follow_up_task_response(task)


@router.post(
    "/organizations/{organization_id}/leads/{lead_id}/quote-drafts",
    response_model=QuoteDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_quote_draft(
    organization_id: str,
    lead_id: str,
    payload: QuoteDraftRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> QuoteDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).create_quote_draft(
            organization_id=organization_id,
            lead_id=lead_id,
            actor_user_id=principal.user_id,
            title=payload.title,
            currency=payload.currency,
            incoterm=payload.incoterm,
            valid_until=payload.valid_until,
            line_items=[item.model_dump() for item in payload.line_items],
            notes=payload.notes,
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
    return quote_draft_response(draft, session)


@router.get("/organizations/{organization_id}/quote-drafts", response_model=list[QuoteDraftResponse])
def list_quote_drafts(
    organization_id: str,
    status_filter: QuoteDraftStatus | None = QuoteDraftStatus.DRAFT,
    limit: int = 20,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[QuoteDraftResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    safe_limit = min(max(limit, 1), 50)
    return [
        quote_draft_response(draft, session)
        for draft, _lead in LeadService(session).list_quote_drafts(
            organization_id=organization_id,
            status_filter=status_filter,
            limit=safe_limit,
        )
    ]


@router.patch("/organizations/{organization_id}/quote-drafts/{draft_id}", response_model=QuoteDraftResponse)
def update_quote_draft(
    organization_id: str,
    draft_id: str,
    payload: QuoteDraftRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> QuoteDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).update_quote_draft(
            draft_id=draft_id,
            organization_id=organization_id,
            title=payload.title,
            currency=payload.currency,
            incoterm=payload.incoterm,
            valid_until=payload.valid_until,
            line_items=[item.model_dump() for item in payload.line_items],
            notes=payload.notes,
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
    return quote_draft_response(draft, session)


@router.post("/organizations/{organization_id}/quote-drafts/{draft_id}/send", response_model=QuoteDraftResponse)
def mark_quote_draft_sent(
    organization_id: str,
    draft_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> QuoteDraftResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        draft = LeadService(session).mark_quote_draft_sent(
            draft_id=draft_id,
            organization_id=organization_id,
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
    return quote_draft_response(draft, session)


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
