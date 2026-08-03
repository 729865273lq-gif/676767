from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.credentials import CredentialCipher, CredentialService
from app.platform.auth import AuthService
from app.platform.models import UserMembership
from app.platform.product_lines import ProductItemNotFound, ProductLineNotFound, ProductLineService
from app.platform.service import OrganizationService, TenantAccessDenied
from app.shared.security import InvalidPrincipalToken, PrincipalTokenCodec, SignedPrincipal
import time

router = APIRouter(prefix="/platform", tags=["platform"])

class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=200)
class LoginRequest(BaseModel):
    email: str
    password: str
class SessionResponse(BaseModel):
    access_token: str
    user_id: str
    organization_id: str


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


class ProductItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=1_000)
    specs: list[str] = Field(default_factory=list, max_length=100)
    image_url: str = Field(default="", max_length=1_000)
    is_published: bool = False


class ProductItemResponse(BaseModel):
    id: str
    product_line_id: str
    name: str
    sku: str
    summary: str
    specs: list[str]
    image_url: str
    is_published: bool


class ProductLineResponse(BaseModel):
    id: str
    name: str
    description: str
    product_keywords: list[str]
    buyer_profiles: list[str]
    target_regions: list[str]
    is_active: bool
    suppliers: list[str]
    product_items: list[ProductItemResponse]


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

@router.post("/auth/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, session: Session = Depends(get_session)) -> SessionResponse:
    try:
        user, organization = AuthService(session).register(payload.organization_name, payload.display_name, payload.email, payload.password)
        session.commit()
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    token = PrincipalTokenCodec(request.app.state.settings.app_secret).issue(user.id, expires_at=int(time.time()) + 86400)
    return SessionResponse(access_token=token, user_id=user.id, organization_id=organization.id)

@router.post("/auth/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, session: Session = Depends(get_session)) -> SessionResponse:
    user = AuthService(session).authenticate(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    membership = session.scalar(select(UserMembership).where(UserMembership.user_id == user.id))
    token = PrincipalTokenCodec(request.app.state.settings.app_secret).issue(user.id, expires_at=int(time.time()) + 86400)
    return SessionResponse(access_token=token, user_id=user.id, organization_id=membership.organization_id)


def product_item_response(product_item) -> ProductItemResponse:
    return ProductItemResponse(
        id=product_item.id,
        product_line_id=product_item.product_line_id,
        name=product_item.name,
        sku=product_item.sku,
        summary=product_item.summary,
        specs=product_item.specs,
        image_url=product_item.image_url,
        is_published=product_item.is_published,
    )


def product_line_response(product_line, suppliers: list[str], product_items: list | None = None) -> ProductLineResponse:
    return ProductLineResponse(
        id=product_line.id,
        name=product_line.name,
        description=product_line.description,
        product_keywords=product_line.product_keywords,
        buyer_profiles=product_line.buyer_profiles,
        target_regions=product_line.target_regions,
        is_active=product_line.is_active,
        suppliers=suppliers,
        product_items=[product_item_response(item) for item in product_items or []],
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
    return product_line_response(product_line, [], [])


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
    items_by_product_line = service.product_items_by_product_line(organization_id)
    return [
        product_line_response(
            product_line,
            suppliers_by_product_line.get(product_line.id, []),
            items_by_product_line.get(product_line.id, []),
        )
        for product_line in service.list_product_lines(organization_id)
    ]


@router.post(
    "/organizations/{organization_id}/product-lines/{product_line_id}/items",
    response_model=ProductItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product_item(
    organization_id: str,
    product_line_id: str,
    payload: ProductItemRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProductItemResponse:
    try:
        product_item = ProductLineService(session).create_product_item(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            product_line_id=product_line_id,
            name=payload.name,
            sku=payload.sku,
            summary=payload.summary,
            specs=payload.specs,
            image_url=payload.image_url,
            is_published=payload.is_published,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return product_item_response(product_item)


@router.get(
    "/organizations/{organization_id}/product-items",
    response_model=list[ProductItemResponse],
)
def list_product_items(
    organization_id: str,
    product_line_id: str | None = None,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ProductItemResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        if product_line_id is not None:
            ProductLineService(session).get_product_line(product_line_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return [
        product_item_response(item)
        for item in ProductLineService(session).list_product_items(
            organization_id=organization_id,
            product_line_id=product_line_id,
        )
    ]


@router.delete(
    "/organizations/{organization_id}/product-items/{product_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product_item(
    organization_id: str,
    product_item_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> None:
    try:
        ProductLineService(session).delete_product_item(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            product_item_id=product_item_id,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductItemNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


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
