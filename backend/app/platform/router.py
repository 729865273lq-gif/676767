from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.platform.credentials import CredentialCipher, CredentialService
from app.platform.product_lines import ProductLineNotFound, ProductLineService
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


class ProductLineRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5_000)
    product_keywords: list[str] = Field(default_factory=list, max_length=100)
    buyer_profiles: list[str] = Field(default_factory=list, max_length=100)
    target_regions: list[str] = Field(default_factory=list, max_length=100)


class ProductLineResponse(BaseModel):
    id: str
    name: str
    description: str
    product_keywords: list[str]
    buyer_profiles: list[str]
    target_regions: list[str]
    is_active: bool
    suppliers: list[str]


class ProductSupplierRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    notes: str = Field(default="", max_length=5_000)


class ProductSupplierResponse(BaseModel):
    id: str
    product_line_id: str
    name: str
    website: str | None
    notes: str


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


def product_line_response(product_line, suppliers: list[str]) -> ProductLineResponse:
    return ProductLineResponse(
        id=product_line.id,
        name=product_line.name,
        description=product_line.description,
        product_keywords=product_line.product_keywords,
        buyer_profiles=product_line.buyer_profiles,
        target_regions=product_line.target_regions,
        is_active=product_line.is_active,
        suppliers=suppliers,
    )


@router.post(
    "/organizations/{organization_id}/product-lines",
    response_model=ProductLineResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product_line(
    organization_id: str,
    payload: ProductLineRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProductLineResponse:
    try:
        product_line = ProductLineService(session).create_product_line(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            product_keywords=payload.product_keywords,
            buyer_profiles=payload.buyer_profiles,
            target_regions=payload.target_regions,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return product_line_response(product_line, [])


@router.get("/organizations/{organization_id}/product-lines", response_model=list[ProductLineResponse])
def list_product_lines(
    organization_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ProductLineResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    service = ProductLineService(session)
    suppliers_by_product_line = service.supplier_names_by_product_line(organization_id)
    return [
        product_line_response(product_line, suppliers_by_product_line.get(product_line.id, []))
        for product_line in service.list_product_lines(organization_id)
    ]


@router.post(
    "/organizations/{organization_id}/product-lines/{product_line_id}/suppliers",
    response_model=ProductSupplierResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_product_supplier(
    organization_id: str,
    product_line_id: str,
    payload: ProductSupplierRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProductSupplierResponse:
    try:
        supplier = ProductLineService(session).add_supplier(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            product_line_id=product_line_id,
            name=payload.name,
            website=payload.website,
            notes=payload.notes,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ProductSupplierResponse(
        id=supplier.id,
        product_line_id=supplier.product_line_id,
        name=supplier.name,
        website=supplier.website,
        notes=supplier.notes,
    )
