from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.llm import ChatProviderError
from app.platform.credentials import CredentialCipher, CredentialService
from app.platform.auth import AuthService
from app.platform.models import Organization, SearchSourcePreference, UserMembership
from app.platform.product_lines import (
    ProductItemNotFound,
    ProductLineInUse,
    ProductLineNotFound,
    ProductLineService,
)
from app.platform.search_keywords import (
    TranslationError,
    country_to_language,
    ensure_keywords_for_search,
    list_search_keywords,
    set_keywords_override,
)
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


class EmailDeliveryStatusResponse(BaseModel):
    provider: str
    configured: bool
    from_email: str | None
    from_name: str
    missing: list[str]


class ConnectorStatusResponse(BaseModel):
    connector_id: str
    label: str
    provider: str
    purpose: str
    configured: bool
    missing: list[str]


class CustomerDevelopmentConnectorsResponse(BaseModel):
    connectors: list[ConnectorStatusResponse]


class SearchSourceResponse(BaseModel):
    source_id: str
    label: str
    provider: str
    category: str
    purpose: str
    base_url: str
    enabled: bool
    configured: bool
    status: str
    missing: list[str]


class SearchSourcesResponse(BaseModel):
    sources: list[SearchSourceResponse]


class UpdateSearchSourceRequest(BaseModel):
    enabled: bool


class ProductLineRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5_000)
    product_keywords: list[str] = Field(default_factory=list, max_length=100)
    buyer_profiles: list[str] = Field(default_factory=list, max_length=100)
    target_regions: list[str] = Field(default_factory=list, max_length=100)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=100)


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
    excluded_keywords: list[str]
    is_active: bool
    suppliers: list[str]
    product_items: list[ProductItemResponse]


class PublicProductItemResponse(BaseModel):
    id: str
    name: str
    sku: str
    summary: str
    specs: list[str]
    image_url: str
    inquiry_product_line_id: str
    inquiry_product_item_id: str


class PublicProductLineResponse(BaseModel):
    id: str
    name: str
    description: str
    product_keywords: list[str]
    buyer_profiles: list[str]
    target_regions: list[str]
    product_items: list[PublicProductItemResponse]


class PublicProductCatalogResponse(BaseModel):
    organization_id: str
    product_lines: list[PublicProductLineResponse]


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


class TranslateSearchKeywordsRequest(BaseModel):
    languages: list[str] = Field(default_factory=list, max_length=20)
    countries: list[str] = Field(default_factory=list, max_length=20)


class SetSearchKeywordsRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=100)


class SearchKeywordResponse(BaseModel):
    id: str
    product_line_id: str
    language: str
    keywords: list[str]
    source: str
    updated_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


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


def search_source_catalog(settings) -> list[dict[str, object]]:
    return [
        {
            "source_id": "tomtom",
            "label": "TomTom 地图客户搜索",
            "provider": "TomTom Search API",
            "category": "map_search",
            "purpose": "按行业和市场搜索海外企业，获取名称、地址、公开电话与官网",
            "base_url": "https://developer.tomtom.com/search-api",
            "status": "needs_config",
            "required": {"TOMTOM_API_KEY": settings.tomtom_api_key},
            "default_enabled": True,
        },
        {
            "source_id": "geoapify",
            "label": "Geoapify 地图客户搜索",
            "provider": "Geoapify Places API",
            "category": "map_search",
            "purpose": "按目标市场搜索企业、工厂和贸易商，并补充公开电话、官网与邮箱",
            "base_url": "https://www.geoapify.com/places-api/",
            "status": "needs_config",
            "required": {"GEOAPIFY_API_KEY": settings.geoapify_api_key},
            "default_enabled": True,
        },
        {
            "source_id": "foursquare",
            "label": "Foursquare 地图客户搜索",
            "provider": "Foursquare Places API",
            "category": "map_search",
            "purpose": "按行业和目标地区搜索商家，并读取公开电话、官网和社交媒体",
            "base_url": "https://foursquare.com/",
            "status": "needs_config",
            "required": {"FOURSQUARE_API_KEY": settings.foursquare_api_key},
            "default_enabled": True,
        },
        {
            "source_id": "openstreetmap",
            "label": "OpenStreetMap 企业搜索",
        "provider": "OpenStreetMap Nominatim + Overpass",
            "category": "map_search",
            "purpose": "搜索全球公开企业地点，并读取官网、电话与社交联系方式标签",
            "base_url": "https://www.openstreetmap.org",
            "status": "ready",
            "required": {},
            "default_enabled": True,
        },
        {
            "source_id": "bocha",
            "label": "公开网页搜索",
            "provider": "Bocha",
            "category": "web_search",
            "purpose": "按产品关键词和目标市场搜索潜在客户官网",
            "base_url": "https://bochaai.com",
            "status": "ready",
            "required": {"BOCHA_API_KEY": settings.bocha_api_key},
            "default_enabled": True,
        },
        {
            "source_id": "google_cse",
            "label": "Google 可编程搜索",
            "provider": "Google Programmable Search",
            "category": "web_search",
            "purpose": "补充全球网页搜索结果，适合行业关键词和地区组合搜索",
            "base_url": "https://programmablesearchengine.google.com",
            "status": "needs_config",
            "required": {
                "GOOGLE_CSE_API_KEY": settings.google_cse_api_key,
                "GOOGLE_CSE_CX": settings.google_cse_cx,
            },
            "default_enabled": False,
        },
        {
            "source_id": "google_places",
            "label": "Google 地图客户搜索",
            "provider": "Google Places",
            "category": "map_search",
            "purpose": "按行业和地区搜索企业，获取官网、公开电话与地图来源链接",
            "base_url": "https://maps.google.com",
            "status": "needs_config",
            "required": {"GOOGLE_PLACES_API_KEY": settings.google_places_api_key},
            "default_enabled": False,
        },
        {
            "source_id": "serpapi",
            "label": "搜索结果 API",
            "provider": "SerpAPI",
            "category": "web_search",
            "purpose": "补充 Google/Bing 等搜索结果，适合多市场客户搜索",
            "base_url": "https://serpapi.com",
            "status": "needs_config",
            "required": {"SERPAPI_API_KEY": settings.serpapi_api_key},
            "default_enabled": False,
        },
        {
            "source_id": "dataforseo",
            "label": "SEO 搜索数据",
            "provider": "DataForSEO",
            "category": "web_search",
            "purpose": "通过搜索数据 API 扩展行业与地区客户发现",
            "base_url": "https://dataforseo.com",
            "status": "needs_config",
            "required": {
                "DATAFORSEO_LOGIN": settings.dataforseo_login,
                "DATAFORSEO_PASSWORD": settings.dataforseo_password,
            },
            "default_enabled": False,
        },
        {
            "source_id": "apollo_companies",
            "label": "公司数据库",
            "provider": "Apollo",
            "category": "company_database",
            "purpose": "按行业、地区和职位线索补充公司与联系人信息",
            "base_url": "https://apollo.io",
            "status": "needs_config",
            "required": {"APOLLO_API_KEY": settings.apollo_api_key},
            "default_enabled": False,
        },
        {
            "source_id": "b2b_directories",
            "label": "B2B 目录网站",
            "provider": "Alibaba / Global Sources / Made-in-China / Europages / Kompass",
            "category": "planned_connector",
            "purpose": "预留外贸目录站接入口，后续按网站逐个实现抓取或 API 导入",
            "base_url": "",
            "status": "planned",
            "required": {},
            "default_enabled": False,
        },
    ]


def search_source_response(source: dict[str, object], preference: SearchSourcePreference | None) -> SearchSourceResponse:
    required = source["required"]
    assert isinstance(required, dict)
    missing = [name for name, value in required.items() if not value]
    status = str(source["status"])
    configured = status == "planned" or not missing
    default_enabled = bool(source["default_enabled"])
    return SearchSourceResponse(
        source_id=str(source["source_id"]),
        label=str(source["label"]),
        provider=str(source["provider"]),
        category=str(source["category"]),
        purpose=str(source["purpose"]),
        base_url=str(source["base_url"]),
        enabled=preference.enabled if preference is not None else default_enabled,
        configured=configured,
        status=status if configured else "needs_config",
        missing=missing,
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


@router.get(
    "/organizations/{organization_id}/email-delivery",
    response_model=EmailDeliveryStatusResponse,
)
def get_email_delivery_status(
    organization_id: str,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> EmailDeliveryStatusResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    settings = request.app.state.settings
    required_fields = {
        "SMTP_HOST": settings.smtp_host,
        "SMTP_USERNAME": settings.smtp_username,
        "SMTP_PASSWORD": settings.smtp_password,
        "SMTP_FROM_EMAIL": settings.smtp_from_email,
    }
    missing = [name for name, value in required_fields.items() if not value]
    return EmailDeliveryStatusResponse(
        provider="smtp",
        configured=len(missing) == 0,
        from_email=settings.smtp_from_email,
        from_name=settings.smtp_from_name,
        missing=missing,
    )


@router.get(
    "/organizations/{organization_id}/customer-development-connectors",
    response_model=CustomerDevelopmentConnectorsResponse,
)
def get_customer_development_connectors(
    organization_id: str,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> CustomerDevelopmentConnectorsResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    settings = request.app.state.settings

    def item(
        *,
        connector_id: str,
        label: str,
        provider: str,
        purpose: str,
        required: dict[str, object | None],
    ) -> ConnectorStatusResponse:
        missing = [name for name, value in required.items() if not value]
        return ConnectorStatusResponse(
            connector_id=connector_id,
            label=label,
            provider=provider,
            purpose=purpose,
            configured=len(missing) == 0,
            missing=missing,
        )

    return CustomerDevelopmentConnectorsResponse(
        connectors=[
            item(
                connector_id="public_search",
                label="公开客户搜索",
                provider="Bocha",
                purpose="按产品和市场搜索潜在客户官网",
                required={"BOCHA_API_KEY": settings.bocha_api_key},
            ),
            item(
                connector_id="map_search_tomtom",
                label="地图客户搜索",
                provider="TomTom",
                purpose="按行业和市场搜索海外企业地点、电话和官网",
                required={"TOMTOM_API_KEY": settings.tomtom_api_key},
            ),
            item(
                connector_id="map_search_geoapify",
                label="地图客户搜索",
                provider="Geoapify",
                purpose="按目标市场搜索企业、工厂和贸易商，并读取公开联系方式",
                required={"GEOAPIFY_API_KEY": settings.geoapify_api_key},
            ),
            item(
                connector_id="map_search_foursquare",
                label="地图客户搜索",
                provider="Foursquare",
                purpose="按行业和市场搜索企业地点、电话、官网与社交媒体",
                required={"FOURSQUARE_API_KEY": settings.foursquare_api_key},
            ),
            item(
                connector_id="customer_database",
                label="客户数据库",
                provider="Apollo",
                purpose="搜索公司、联系人和职位信息",
                required={"APOLLO_API_KEY": settings.apollo_api_key},
            ),
            item(
                connector_id="email_finder",
                label="邮箱查找",
                provider="Hunter",
                purpose="按公司域名查找可联系邮箱",
                required={"HUNTER_API_KEY": settings.hunter_api_key},
            ),
            item(
                connector_id="email_verifier_zerobounce",
                label="邮箱验证",
                provider="ZeroBounce",
                purpose="发信前验证邮箱有效性",
                required={"ZEROBOUNCE_API_KEY": settings.zerobounce_api_key},
            ),
            item(
                connector_id="email_verifier_neverbounce",
                label="备用邮箱验证",
                provider="NeverBounce",
                purpose="发信前验证邮箱有效性",
                required={"NEVERBOUNCE_API_KEY": settings.neverbounce_api_key},
            ),
            item(
                connector_id="outbound_email",
                label="开发信发送",
                provider="SMTP",
                purpose="人工确认后发送开发信",
                required={
                    "SMTP_HOST": settings.smtp_host,
                    "SMTP_USERNAME": settings.smtp_username,
                    "SMTP_PASSWORD": settings.smtp_password,
                    "SMTP_FROM_EMAIL": settings.smtp_from_email,
                },
            ),
        ]
    )


@router.get(
    "/organizations/{organization_id}/search-sources",
    response_model=SearchSourcesResponse,
)
def list_search_sources(
    organization_id: str,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> SearchSourcesResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    preferences = {
        preference.source_id: preference
        for preference in session.scalars(
            select(SearchSourcePreference).where(SearchSourcePreference.organization_id == organization_id)
        )
    }
    return SearchSourcesResponse(
        sources=[
            search_source_response(source, preferences.get(str(source["source_id"])))
            for source in search_source_catalog(request.app.state.settings)
        ]
    )


@router.patch(
    "/organizations/{organization_id}/search-sources/{source_id}",
    response_model=SearchSourceResponse,
)
def update_search_source(
    organization_id: str,
    source_id: str,
    payload: UpdateSearchSourceRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> SearchSourceResponse:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    source = next(
        (item for item in search_source_catalog(request.app.state.settings) if item["source_id"] == source_id),
        None,
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="search source not found")
    preference = session.scalar(
        select(SearchSourcePreference).where(
            SearchSourcePreference.organization_id == organization_id,
            SearchSourcePreference.source_id == source_id,
        )
    )
    if preference is None:
        preference = SearchSourcePreference(
            organization_id=organization_id,
            source_id=source_id,
            enabled=payload.enabled,
        )
        session.add(preference)
    else:
        preference.enabled = payload.enabled
    session.commit()
    return search_source_response(source, preference)


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
        excluded_keywords=product_line.excluded_keywords,
        is_active=product_line.is_active,
        suppliers=suppliers,
        product_items=[product_item_response(item) for item in product_items or []],
    )


def public_product_item_response(product_item) -> PublicProductItemResponse:
    return PublicProductItemResponse(
        id=product_item.id,
        name=product_item.name,
        sku=product_item.sku,
        summary=product_item.summary,
        specs=product_item.specs,
        image_url=product_item.image_url,
        inquiry_product_line_id=product_item.product_line_id,
        inquiry_product_item_id=product_item.id,
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
            excluded_keywords=payload.excluded_keywords,
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


@router.delete(
    "/organizations/{organization_id}/product-lines/{product_line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product_line(
    organization_id: str,
    product_line_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> None:
    try:
        ProductLineService(session).delete_product_line(
            actor_user_id=principal.user_id,
            organization_id=organization_id,
            product_line_id=product_line_id,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ProductLineInUse as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get(
    "/public/organizations/{organization_id}/product-catalog",
    response_model=PublicProductCatalogResponse,
)
def public_product_catalog(
    organization_id: str,
    session: Session = Depends(get_session),
) -> PublicProductCatalogResponse:
    if session.get(Organization, organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")
    service = ProductLineService(session)
    items_by_product_line = service.product_items_by_product_line(organization_id)
    product_lines: list[PublicProductLineResponse] = []
    for product_line in service.list_product_lines(organization_id):
        public_items = [
            public_product_item_response(product_item)
            for product_item in items_by_product_line.get(product_line.id, [])
            if product_item.is_published
        ]
        if public_items:
            product_lines.append(
                PublicProductLineResponse(
                    id=product_line.id,
                    name=product_line.name,
                    description=product_line.description,
                    product_keywords=product_line.product_keywords,
                    buyer_profiles=product_line.buyer_profiles,
                    target_regions=product_line.target_regions,
                    product_items=public_items,
                )
            )
    return PublicProductCatalogResponse(organization_id=organization_id, product_lines=product_lines)


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


def search_keyword_response(row) -> SearchKeywordResponse:
    return SearchKeywordResponse(
        id=row.id,
        product_line_id=row.product_line_id,
        language=row.language,
        keywords=row.keywords,
        source=row.source.value,
        updated_by_user_id=row.updated_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _resolve_translation_languages(payload: TranslateSearchKeywordsRequest) -> list[str]:
    if payload.languages:
        return list(
            dict.fromkeys(
                language.strip().casefold() for language in payload.languages if language.strip()
            )
        )
    if payload.countries:
        return list(
            dict.fromkeys(
                country_to_language(country) for country in payload.countries if country.strip()
            )
        )
    return ["en"]


@router.post(
    "/organizations/{organization_id}/product-lines/{product_line_id}/search-keywords/translate",
    response_model=list[SearchKeywordResponse],
)
def translate_search_keywords(
    organization_id: str,
    product_line_id: str,
    payload: TranslateSearchKeywordsRequest,
    request: Request,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[SearchKeywordResponse]:
    try:
        OrganizationService(session).require_admin(principal.user_id, organization_id)
        product_line = ProductLineService(session).get_product_line(product_line_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    languages = _resolve_translation_languages(payload)
    llm = getattr(request.app.state, "llm_connector", None)
    rows = []
    missing = []
    try:
        for language in languages:
            row = ensure_keywords_for_search(session, llm, product_line, language)
            if row is None:
                missing.append(language)
            else:
                rows.append(row)
    except (TranslationError, ChatProviderError) as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    if missing:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"翻译服务未配置，无法翻译：{', '.join(missing)}",
        )
    session.commit()
    return [search_keyword_response(row) for row in rows]


@router.get(
    "/organizations/{organization_id}/product-lines/{product_line_id}/search-keywords",
    response_model=list[SearchKeywordResponse],
)
def list_product_line_search_keywords(
    organization_id: str,
    product_line_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[SearchKeywordResponse]:
    try:
        OrganizationService(session).require_membership(principal.user_id, organization_id)
        product_line = ProductLineService(session).get_product_line(product_line_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return [search_keyword_response(row) for row in list_search_keywords(session, product_line)]


@router.put(
    "/organizations/{organization_id}/product-lines/{product_line_id}/search-keywords/{language}",
    response_model=SearchKeywordResponse,
)
def override_search_keywords(
    organization_id: str,
    product_line_id: str,
    language: str,
    payload: SetSearchKeywordsRequest,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> SearchKeywordResponse:
    try:
        OrganizationService(session).require_admin(principal.user_id, organization_id)
        product_line = ProductLineService(session).get_product_line(product_line_id, organization_id)
        row = set_keywords_override(session, product_line, language, payload.keywords, principal.user_id)
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ProductLineNotFound as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return search_keyword_response(row)
