from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.platform.credentials import CredentialCipher, CredentialService
from app.platform.service import OrganizationService, TenantAccessDenied

router = APIRouter(prefix="/platform", tags=["platform"])


class CreateCredentialRequest(BaseModel):
    connector_type: str = Field(min_length=1, max_length=100)
    key_label: str = Field(min_length=1, max_length=200)
    secret: str = Field(min_length=1)


class CredentialResponse(BaseModel):
    id: str
    connector_type: str
    key_label: str
    last_four: str


def get_session(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


def current_user_id(x_user_id: str = Header(alias="X-User-Id")) -> str:
    return x_user_id


@router.get("/organizations/{organization_id}/membership")
def get_membership(
    organization_id: str,
    user_id: str = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    try:
        membership = OrganizationService(session).require_membership(user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return {"organization_id": membership.organization_id, "role": membership.role.value}


@router.post(
    "/organizations/{organization_id}/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_credential(
    organization_id: str,
    payload: CreateCredentialRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> CredentialResponse:
    try:
        credential = CredentialService(
            session, CredentialCipher(request.app.state.settings.credential_encryption_key)
        ).create(
            actor_user_id=user_id,
            organization_id=organization_id,
            connector_type=payload.connector_type,
            key_label=payload.key_label,
            secret=payload.secret,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return CredentialResponse(
        id=credential.id,
        connector_type=credential.connector_type,
        key_label=credential.key_label,
        last_four=credential.last_four,
    )
