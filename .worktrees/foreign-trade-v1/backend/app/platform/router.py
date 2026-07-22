from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.platform.credentials import CredentialCipher, CredentialService
from app.platform.service import OrganizationService, TenantAccessDenied
from app.shared.security import InvalidPrincipalToken, PrincipalTokenCodec, SignedPrincipal

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


def current_principal(
    request: Request, authorization: str | None = Header(default=None)
) -> SignedPrincipal:
    scheme, _, token = authorization.partition(" ") if authorization else ("", "", "")
    if scheme.lower() != "bearer" or not token:
        raise _authentication_error()
    try:
        return PrincipalTokenCodec(request.app.state.settings.app_secret).verify(token)
    except InvalidPrincipalToken as error:
        raise _authentication_error() from error


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.get("/organizations/{organization_id}/membership")
def get_membership(
    organization_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    try:
        membership = OrganizationService(session).require_membership(principal.user_id, organization_id)
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
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> CredentialResponse:
    try:
        credential = CredentialService(
            session, CredentialCipher(request.app.state.settings.credential_encryption_key)
        ).create(
            actor_user_id=principal.user_id,
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
