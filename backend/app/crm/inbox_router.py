from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.connectors.email import ImapConfigurationError, ImapConnector, ImapError
from app.connectors.llm import ChatConfigurationError, OpenAICompatibleChatConnector
from app.crm.inbox import InboxService
from app.crm.models import InboundMessage
from app.platform.router import current_principal, get_session
from app.platform.service import OrganizationService, TenantAccessDenied
from app.shared.security import SignedPrincipal

router = APIRouter(tags=["inbox"])


class InboxSyncResponse(BaseModel):
    organization_id: str
    synced: int


class InboxMessageListItem(BaseModel):
    id: str
    provider_message_id: str
    sender_email: str
    sender_name: str
    subject: str
    received_at: datetime
    intent: str
    intent_confidence: float
    suggested_reply: str
    follow_up_task_id: str | None
    due_at: datetime | None
    created_at: datetime


class InboxMessageDetail(BaseModel):
    id: str
    provider_message_id: str
    thread_id: str
    sender_email: str
    sender_name: str
    subject: str
    body_text: str
    received_at: datetime
    intent: str
    intent_confidence: float
    analysis_rationale: str
    suggested_reply: str
    follow_up_task_id: str | None
    due_at: datetime | None
    linked_company_name: str | None
    created_at: datetime


class FollowUpDoneResponse(BaseModel):
    message_id: str
    follow_up_status: str


def _require_membership(principal: SignedPrincipal, organization_id: str, session: Session) -> None:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


def _require_admin(principal: SignedPrincipal, organization_id: str, session: Session) -> None:
    try:
        OrganizationService(session).require_admin(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


def _imap_connector(request: Request) -> ImapConnector:
    injected = getattr(request.app.state, "imap_connector", None)
    if injected is not None:
        return injected
    return ImapConnector.from_settings(request.app.state.settings)


def _llm_connector(request: Request) -> OpenAICompatibleChatConnector | None:
    injected = getattr(request.app.state, "llm_connector", None)
    if injected is not None:
        return injected
    try:
        return OpenAICompatibleChatConnector.from_settings(request.app.state.settings)
    except ChatConfigurationError:
        return None


def _list_item(message: InboundMessage, service: InboxService) -> InboxMessageListItem:
    return InboxMessageListItem(
        id=message.id,
        provider_message_id=message.provider_message_id,
        sender_email=message.sender_email,
        sender_name=message.sender_name,
        subject=message.subject,
        received_at=message.received_at,
        intent=message.intent,
        intent_confidence=message.intent_confidence,
        suggested_reply=message.suggested_reply,
        follow_up_task_id=message.follow_up_task_id,
        due_at=service.message_due_at(message),
        created_at=message.created_at,
    )


def _detail(message: InboundMessage, service: InboxService) -> InboxMessageDetail:
    return InboxMessageDetail(
        id=message.id,
        provider_message_id=message.provider_message_id,
        thread_id=message.thread_id,
        sender_email=message.sender_email,
        sender_name=message.sender_name,
        subject=message.subject,
        body_text=message.body_text,
        received_at=message.received_at,
        intent=message.intent,
        intent_confidence=message.intent_confidence,
        analysis_rationale=message.analysis_rationale,
        suggested_reply=message.suggested_reply,
        follow_up_task_id=message.follow_up_task_id,
        due_at=service.message_due_at(message),
        linked_company_name=service.linked_company_name(message),
        created_at=message.created_at,
    )


@router.post(
    "/organizations/{organization_id}/inbox/sync",
    response_model=InboxSyncResponse,
)
def sync_inbox(
    organization_id: str,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> InboxSyncResponse:
    _require_admin(principal, organization_id, session)
    try:
        imap_connector = _imap_connector(request)
    except ImapConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    service = InboxService(session, imap_connector, _llm_connector(request))
    try:
        synced = service.sync_organization_mailbox(organization_id)
    except ImapError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return InboxSyncResponse(organization_id=organization_id, synced=synced)


@router.get(
    "/organizations/{organization_id}/inbox",
    response_model=list[InboxMessageListItem],
)
def list_inbox(
    organization_id: str,
    intent: str | None = None,
    has_follow_up: bool | None = None,
    due_from: datetime | None = None,
    due_before: datetime | None = None,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[InboxMessageListItem]:
    _require_membership(principal, organization_id, session)
    service = InboxService(session)
    messages = service.list_messages(
        organization_id,
        intent=intent,
        has_follow_up=has_follow_up,
        due_from=due_from,
        due_before=due_before,
    )
    return [_list_item(message, service) for message in messages]


@router.get(
    "/organizations/{organization_id}/inbox/{message_id}",
    response_model=InboxMessageDetail,
)
def get_inbox_message(
    organization_id: str,
    message_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> InboxMessageDetail:
    _require_membership(principal, organization_id, session)
    service = InboxService(session)
    try:
        message = service.get_message(message_id, organization_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return _detail(message, service)


@router.post(
    "/organizations/{organization_id}/inbox/{message_id}/follow-up/done",
    response_model=FollowUpDoneResponse,
)
def mark_follow_up_done(
    organization_id: str,
    message_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> FollowUpDoneResponse:
    _require_membership(principal, organization_id, session)
    service = InboxService(session)
    try:
        service.mark_follow_up_done(message_id, organization_id, principal.user_id)
        session.commit()
    except LookupError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return FollowUpDoneResponse(message_id=message_id, follow_up_status="done")
