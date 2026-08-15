import time

from datetime import datetime, timezone

from cryptography.fernet import Fernet

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.base.contracts import SearchResult
from app.connectors.contact_discovery import DiscoveredContact
from app.connectors.email_verification import EmailVerificationResult
from app.connectors.geography import AdministrativeArea
from app.main import create_app
from app.crm.models import (
    CRMContact,
    EmailDraftStatus,
    Lead,
    LeadBucket,
    LeadEvidence,
    LeadStatus,
    WebsiteInquiryStatus,
)
from app.platform.models import (
    ConnectorCredential,
    MembershipRole,
    Organization,
    ProductItem,
    ProductLine,
    ProductSupplier,
    SearchSourcePreference,
    User,
    UserMembership,
)
from app.shared.config import Settings
from app.shared.db import Base
from app.shared.security import PrincipalTokenCodec
from app.workflow.models import WorkflowRun, WorkflowState


APP_SECRET = "a-local-test-secret-that-is-long-enough"


class FakeEmailConnector:
    connector_id = "fake-email"

    def __init__(self) -> None:
        self.sent_messages: list[tuple[object, str]] = []

    def send(self, message: object, idempotency_key: str) -> str:
        self.sent_messages.append((message, idempotency_key))
        return "fake-provider-message-id"


class FakeContactDiscoveryConnector:
    connector_id = "fake-contact-discovery"

    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    def discover(self, domain: str, limit: int) -> list[DiscoveredContact]:
        self.requests.append((domain, limit))
        return [
            DiscoveredContact(
                name="Anna Weber",
                title="Purchasing Manager",
                email="anna@follow-up.example",
                phone="+49 30 123456",
                linkedin_url="https://linkedin.com/in/anna-weber",
                confidence=92,
                verification_status="valid",
                source="Hunter",
            ),
            DiscoveredContact(
                name="Buyer Desk",
                title="Procurement",
                email="buyer@follow-up.example",
                confidence=77,
                verification_status="accept_all",
                source="Hunter",
            ),
        ]


class FakeEmailVerificationConnector:
    connector_id = "fake-email-verification"

    def __init__(self) -> None:
        self.requests: list[str] = []

    def verify(self, email: str) -> EmailVerificationResult:
        self.requests.append(email)
        return EmailVerificationResult(
            email=email,
            status="valid",
            sub_status="",
            provider="ZeroBounce",
            deliverable=True,
        )


class FakeSearchConnector:
    connector_id = "fake-search"

    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.requests.append((query, limit))
        return [
            SearchResult(
                url="https://buyer-search.example/catalog",
                title="Buyer Search GmbH",
                snippet="Industrial lighting importer and distributor.",
                phone="+49 30 998877",
                source_url="https://maps.google.com/?cid=buyer-search",
            )
        ]


class FakeAdministrativeAreaConnector:
    async def resolve(self, query: str) -> AdministrativeArea:
        assert query == "北京"
        return AdministrativeArea(
            scope_id="beijing-place",
            name="北京市",
            formatted="北京市, 中国",
            search_label="北京市, 中国",
            country_code="CN",
            level="city",
        )

    async def subdivisions(self, area: AdministrativeArea) -> list[AdministrativeArea]:
        assert area.scope_id == "beijing-place"
        return [
            AdministrativeArea(
                scope_id="chaoyang-place",
                name="朝阳区",
                formatted="朝阳区, 中国",
                search_label="朝阳区, 北京市, 中国",
                country_code="CN",
                level="district",
            ),
            AdministrativeArea(
                scope_id="fengtai-place",
                name="丰台区",
                formatted="丰台区, 中国",
                search_label="丰台区, 北京市, 中国",
                country_code="CN",
                level="district",
            ),
        ]


def bearer_headers(user_id: str, expires_at: int | None = None) -> dict[str, str]:
    token = PrincipalTokenCodec(APP_SECRET).issue(
        user_id,
        expires_at=expires_at or int(time.time()) + 3_600,
    )
    return {"Authorization": f"Bearer {token}"}


def configured_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    acme = Organization(name="Acme Export")
    globex = Organization(name="Globex Import")
    member = User(email="member@acme.example", display_name="Acme Member")
    admin = User(email="admin@acme.example", display_name="Acme Admin")
    with factory.begin() as session:
        session.add_all([acme, globex, member, admin])
        session.flush()
        session.add_all(
            [
                UserMembership(
                    user_id=member.id,
                    organization_id=acme.id,
                    role=MembershipRole.MEMBER,
                ),
                UserMembership(
                    user_id=admin.id,
                    organization_id=acme.id,
                    role=MembershipRole.ADMIN,
                ),
            ]
        )
    settings = Settings(
        app_secret=APP_SECRET,
        credential_encryption_key=Fernet.generate_key().decode(),
        database_url="sqlite://",
        redis_url="redis://redis:6379/0",
        s3_endpoint="http://minio:9000",
    )
    email_connector = FakeEmailConnector()
    contact_discovery_connector = FakeContactDiscoveryConnector()
    email_verification_connector = FakeEmailVerificationConnector()
    search_connector = FakeSearchConnector()
    client = TestClient(
        create_app(
            session_factory=factory,
            settings=settings,
            email_connector=email_connector,
            contact_discovery_connector=contact_discovery_connector,
            email_verification_connector=email_verification_connector,
            search_connector=search_connector,
        )
    )
    client.email_connector = email_connector  # type: ignore[attr-defined]
    client.contact_discovery_connector = contact_discovery_connector  # type: ignore[attr-defined]
    client.email_verification_connector = email_verification_connector  # type: ignore[attr-defined]
    client.search_connector = search_connector  # type: ignore[attr-defined]
    client.app.state.administrative_area_connector = FakeAdministrativeAreaConnector()
    client.acme_id = acme.id  # type: ignore[attr-defined]
    client.globex_id = globex.id  # type: ignore[attr-defined]
    client.member_id = member.id  # type: ignore[attr-defined]
    client.admin_id = admin.id  # type: ignore[attr-defined]
    return client, factory


def test_membership_route_denies_cross_tenant_read() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.globex_id}/membership",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 403


def test_location_resolver_returns_subdivisions_and_search_coverage() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Bearings")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        session.add(
            WorkflowRun(
                organization_id=client.acme_id,  # type: ignore[attr-defined]
                agent_id="customer",
                agent_version="1.1.0",
                state=WorkflowState.COMPLETED,
                input_json={
                    "product_line_id": product_line.id,
                    "target_market": "朝阳区, 北京市, 中国",
                    "location_scope_id": "chaoyang-place",
                },
                output_json={},
                idempotency_key="existing-chaoyang-search",
            )
        )
        product_line_id = product_line.id

    response = client.post(
        f"/discovery/organizations/{client.acme_id}/locations/resolve",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"query": "北京", "product_line_id": product_line_id},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["area"]["name"] == "北京市"
    subdivisions = {item["name"]: item for item in result["subdivisions"]}
    assert subdivisions["朝阳区"]["search_count"] == 1
    assert subdivisions["朝阳区"]["last_searched_at"]
    assert subdivisions["丰台区"]["search_count"] == 0


def test_discovery_blocks_duplicate_administrative_area_without_override() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            name="Bearings",
            product_keywords=["bearing"],
        )
        session.add(product_line)
        session.flush()
        session.add(
            WorkflowRun(
                organization_id=client.acme_id,  # type: ignore[attr-defined]
                agent_id="customer",
                agent_version="1.1.0",
                state=WorkflowState.COMPLETED,
                input_json={
                    "product_line_id": product_line.id,
                    "target_market": "朝阳区, 北京市, 中国",
                    "location_scope_id": "chaoyang-place",
                },
                output_json={},
                idempotency_key="first-chaoyang-search",
            )
        )
        product_line_id = product_line.id

    response = client.post(
        f"/discovery/organizations/{client.acme_id}/runs",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "product_line_id": product_line_id,
            "target_market": "朝阳区, 北京市, 中国",
            "location_scope_id": "chaoyang-place",
            "location_country_code": "CN",
            "limit": 20,
            "idempotency_key": "second-chaoyang-search",
        },
    )

    assert response.status_code == 409
    assert "已经搜索过该行政区" in response.json()["detail"]


def test_caller_controlled_user_header_cannot_impersonate_member() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers={"X-User-Id": client.member_id},  # type: ignore[attr-defined]
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_valid_signed_principal_can_read_own_membership() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    assert response.json()["role"] == "member"


def test_email_delivery_status_reports_missing_smtp_configuration() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.acme_id}/email-delivery",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "smtp",
        "configured": False,
        "from_email": None,
        "from_name": "Trade Axis",
        "missing": ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"],
    }
    assert "replace-with" not in response.text.lower()


def test_customer_development_connectors_report_configuration_status() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.acme_id}/customer-development-connectors",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    items = {item["connector_id"]: item for item in response.json()["connectors"]}
    assert set(items) == {
        "public_search",
        "map_search_tomtom",
        "map_search_geoapify",
        "map_search_foursquare",
        "customer_database",
        "email_finder",
        "email_verifier_zerobounce",
        "email_verifier_neverbounce",
        "outbound_email",
    }
    assert items["public_search"]["provider"] == "Bocha"
    assert items["map_search_tomtom"]["missing"] == ["TOMTOM_API_KEY"]
    assert items["map_search_geoapify"]["missing"] == ["GEOAPIFY_API_KEY"]
    assert items["map_search_foursquare"]["missing"] == ["FOURSQUARE_API_KEY"]
    assert items["customer_database"]["missing"] == ["APOLLO_API_KEY"]
    assert items["email_finder"]["missing"] == ["HUNTER_API_KEY"]
    assert items["outbound_email"]["missing"] == [
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
    ]
    assert "secret" not in response.text.lower()


def test_search_sources_can_be_listed_and_toggled_without_exposing_secrets() -> None:
    client, factory = configured_client()

    listed = client.get(
        f"/platform/organizations/{client.acme_id}/search-sources",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    toggled = client.patch(
        f"/platform/organizations/{client.acme_id}/search-sources/google_cse",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"enabled": True},
    )
    listed_after_toggle = client.get(
        f"/platform/organizations/{client.acme_id}/search-sources",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    missing = client.patch(
        f"/platform/organizations/{client.acme_id}/search-sources/not-real",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"enabled": True},
    )

    assert listed.status_code == 200
    sources = {item["source_id"]: item for item in listed.json()["sources"]}
    assert "bocha" in sources
    assert "google_cse" in sources
    assert "google_places" in sources
    assert "openstreetmap" in sources
    assert "tomtom" in sources
    assert "geoapify" in sources
    assert "foursquare" in sources
    assert sources["openstreetmap"]["enabled"] is True
    assert sources["openstreetmap"]["configured"] is True
    assert sources["bocha"]["enabled"] is True
    assert sources["bocha"]["configured"] is False
    assert sources["bocha"]["missing"] == ["BOCHA_API_KEY"]
    assert sources["google_places"]["missing"] == ["GOOGLE_PLACES_API_KEY"]
    assert sources["tomtom"]["enabled"] is True
    assert sources["tomtom"]["missing"] == ["TOMTOM_API_KEY"]
    assert sources["geoapify"]["enabled"] is True
    assert sources["geoapify"]["missing"] == ["GEOAPIFY_API_KEY"]
    assert sources["foursquare"]["enabled"] is True
    assert sources["foursquare"]["missing"] == ["FOURSQUARE_API_KEY"]
    assert toggled.status_code == 200
    assert toggled.json()["source_id"] == "google_cse"
    assert toggled.json()["enabled"] is True
    after_toggle = {item["source_id"]: item for item in listed_after_toggle.json()["sources"]}
    assert after_toggle["google_cse"]["enabled"] is True
    assert missing.status_code == 404
    assert "local-session-token" not in listed.text
    assert "secret" not in listed.text.lower()
    with factory() as session:
        preference = session.scalar(
            select(SearchSourcePreference).where(
                SearchSourcePreference.organization_id == client.acme_id,  # type: ignore[attr-defined]
                SearchSourcePreference.source_id == "google_cse",
            )
        )
    assert preference is not None
    assert preference.enabled is True


def test_discovery_run_uses_configured_search_connector_and_saves_leads() -> None:
    client, factory = configured_client()
    product_line = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={
            "name": "Industrial LED Lighting",
            "product_keywords": ["LED floodlight"],
            "buyer_profiles": ["distributor"],
            "target_regions": ["Germany"],
        },
    )

    discovery = client.post(
        f"/discovery/organizations/{client.acme_id}/runs",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "idempotency_key": "search-source-route",
            "product_line_id": product_line.json()["id"],
            "target_market": "Germany",
            "buyer_profile": "distributor",
            "limit": 5,
        },
    )

    assert discovery.status_code == 201
    assert discovery.json()["lead_count"] == 1
    assert discovery.json()["state"] == "completed"
    assert client.search_connector.requests == [  # type: ignore[attr-defined]
        ("LED floodlight distributor Germany", 5),
        ("industrial lighting wholesaler Germany", 5),
        ("LED lighting importer Germany", 5),
        ("industrial lighting wholesaler Berlin Germany", 5),
    ]
    with factory() as session:
        lead = session.scalar(select(Lead).where(Lead.company_name == "Buyer Search GmbH"))
        contact = session.scalar(select(CRMContact).where(CRMContact.lead_id == lead.id)) if lead else None
    assert lead is not None
    assert lead.website == "https://buyer-search.example/catalog"
    assert contact is not None
    assert contact.phone == "+49 30 998877"
    assert contact.source_url == "https://maps.google.com/?cid=buyer-search"


def test_tampered_or_expired_principal_is_rejected() -> None:
    client, _ = configured_client()
    valid = bearer_headers(client.member_id)["Authorization"]
    expired = bearer_headers(client.member_id, expires_at=int(time.time()) - 1)

    tampered = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers={"Authorization": f"{valid}x"},
    )
    expired_response = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers=expired,
    )

    assert tampered.status_code == 401
    assert expired_response.status_code == 401


def test_credential_route_rejects_member_and_hides_admin_secret() -> None:
    client, factory = configured_client()
    payload = {"connector_type": "gmail", "key_label": "sales", "secret": "api-secret-value"}

    denied = client.post(
        f"/platform/organizations/{client.acme_id}/credentials",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json=payload,
    )
    approved = client.post(
        f"/platform/organizations/{client.acme_id}/credentials",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json=payload,
    )
    with factory() as session:
        credential = session.scalar(select(ConnectorCredential))

    assert denied.status_code == 403
    assert approved.status_code == 201
    assert "api-secret-value" not in approved.text
    assert credential is not None
    assert credential.ciphertext != "api-secret-value"


def test_lifespan_builds_runtime_session_factory_from_safe_settings(monkeypatch) -> None:
    monkeypatch.setenv("APP_SECRET", "a-local-test-secret-that-is-long-enough")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    with TestClient(create_app()) as client:
        assert client.app.state.settings.database_url == "sqlite+pysqlite:///:memory:"
        assert client.app.state.session_factory is not None


def test_product_line_routes_enforce_roles_and_organization_scope() -> None:
    client, _ = configured_client()
    payload = {
        "name": "Industrial LED Lighting",
        "description": "Commercial and industrial retrofit lighting.",
        "product_keywords": ["LED floodlight", "warehouse lighting", "LED floodlight"],
        "buyer_profiles": ["distributor", "project buyer"],
        "target_regions": ["Europe", "North America"],
        "excluded_keywords": ["manufacturer", "jobs", "manufacturer"],
    }

    denied = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json=payload,
    )
    created = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json=payload,
    )
    product_line_id = created.json()["id"]
    supplier = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/suppliers",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"name": "NOVA Lighting Factory", "website": "https://nova.example"},
    )
    denied_item = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/items",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"name": "LED Floodlight 200W"},
    )
    product_item = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/items",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={
            "name": "LED Floodlight 200W",
            "sku": "FL-200W",
            "summary": "High-output outdoor LED floodlight.",
            "specs": ["200W", "IP66", "CE"],
            "image_url": "https://assets.example/floodlight.jpg",
            "is_published": True,
        },
    )
    unpublished_item = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/items",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={
            "name": "Private Sample Driver",
            "sku": "DRV-SAMPLE",
            "summary": "Internal sample only.",
            "specs": ["private"],
            "is_published": False,
        },
    )
    listed_items = client.get(
        f"/platform/organizations/{client.acme_id}/product-items?product_line_id={product_line_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    listed = client.get(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    cross_tenant = client.get(
        f"/platform/organizations/{client.globex_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    public_catalog = client.get(
        f"/platform/public/organizations/{client.acme_id}/product-catalog",  # type: ignore[attr-defined]
    )
    missing_catalog = client.get("/platform/public/organizations/missing-org/product-catalog")

    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["product_keywords"] == ["LED floodlight", "warehouse lighting"]
    assert created.json()["excluded_keywords"] == ["manufacturer", "jobs"]
    assert supplier.status_code == 201
    assert denied_item.status_code == 403
    assert product_item.status_code == 201
    assert unpublished_item.status_code == 201
    assert product_item.json()["sku"] == "FL-200W"
    assert listed_items.status_code == 200
    assert {item["name"] for item in listed_items.json()} == {"LED Floodlight 200W", "Private Sample Driver"}
    assert listed.status_code == 200
    assert listed.json()[0]["suppliers"] == ["NOVA Lighting Factory"]
    listed_item_by_name = {item["name"]: item for item in listed.json()[0]["product_items"]}
    assert listed_item_by_name["LED Floodlight 200W"]["summary"] == "High-output outdoor LED floodlight."
    assert cross_tenant.status_code == 403
    assert public_catalog.status_code == 200
    assert missing_catalog.status_code == 404
    public_line = public_catalog.json()["product_lines"][0]
    assert public_line["name"] == "Industrial LED Lighting"
    assert "suppliers" not in public_line
    assert [item["name"] for item in public_line["product_items"]] == ["LED Floodlight 200W"]
    assert public_line["product_items"][0]["inquiry_product_item_id"] == product_item.json()["id"]

    deleted_item = client.delete(
        f"/platform/organizations/{client.acme_id}/product-items/{product_item.json()['id']}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
    )
    with client.app.state.session_factory() as session:
        removed = session.get(ProductItem, product_item.json()["id"])

    assert deleted_item.status_code == 204
    assert removed is None


def test_product_line_delete_requires_admin_and_removes_nested_catalog() -> None:
    client, factory = configured_client()
    created = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"name": "Temporary Product Line"},
    )
    product_line_id = created.json()["id"]
    supplier = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/suppliers",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"name": "Temporary Supplier"},
    )
    product_item = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/items",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"name": "Temporary Product"},
    )

    denied = client.delete(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    deleted = client.delete(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
    )

    with factory() as session:
        removed_line = session.get(ProductLine, product_line_id)
        removed_supplier = session.get(ProductSupplier, supplier.json()["id"])
        removed_item = session.get(ProductItem, product_item.json()["id"])

    assert denied.status_code == 403
    assert deleted.status_code == 204
    assert removed_line is None
    assert removed_supplier is None
    assert removed_item is None


def test_product_line_delete_rejects_lines_linked_to_customer_leads() -> None:
    client, factory = configured_client()
    created = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={
            "name": "Active Customer Product Line",
            "product_keywords": ["industrial lighting"],
        },
    )
    product_line_id = created.json()["id"]
    discovery = client.post(
        f"/discovery/organizations/{client.acme_id}/runs",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "idempotency_key": "product-line-delete-guard",
            "product_line_id": product_line_id,
            "target_market": "Malaysia",
            "limit": 5,
        },
    )

    deleted = client.delete(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
    )

    with factory() as session:
        retained_line = session.get(ProductLine, product_line_id)
        retained_lead = session.scalar(select(Lead).where(Lead.product_line_id == product_line_id))

    assert discovery.status_code == 201
    assert deleted.status_code == 409
    assert "customer lead" in deleted.json()["detail"]
    assert retained_line is not None
    assert retained_lead is not None


def test_discovery_lead_routes_return_evidence_only_within_the_organization() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="customer",
            agent_version="1.0.0",
            input_json={},
            idempotency_key="lead-route-run",
        )
        session.add(workflow_run)
        session.flush()
        lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="LumenHaus GmbH",
            website="https://lumenhaus.example",
            canonical_domain="lumenhaus.example",
            target_market="Germany",
            buyer_profile="distributor",
            score=60,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            reasons=["product or business fit evidence recorded"],
            missing_signals=["usable contact channel"],
        )
        session.add(lead)
        session.flush()
        session.add(
            LeadEvidence(
                lead_id=lead.id,
                source_url=lead.website,
                source_excerpt="Commercial lighting distributor",
                signal_name="search_result",
            )
        )
    response = client.get(
        f"/discovery/organizations/{client.acme_id}/leads?bucket=needs_enrichment",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    detail = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead.id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    cross_tenant = client.get(
        f"/discovery/organizations/{client.globex_id}/leads",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    assert response.json()[0]["bucket"] == "needs_enrichment"
    assert response.json()[0]["last_discovered_at"]
    assert response.json()[0]["created_at"]
    assert detail.json()["evidence"][0]["source_excerpt"] == "Commercial lighting distributor"
    assert cross_tenant.status_code == 403


def test_manual_customer_routes_create_and_delete_within_the_organization() -> None:
    client, _ = configured_client()
    with client.app.state.session_factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        product_line_id = product_line.id

    payload = {
        "product_line_id": product_line_id,
        "company_name": "Manual Import GmbH",
        "website": "manual-import.example",
        "target_market": "Germany",
        "buyer_profile": "Distributor",
        "notes": "Met at Canton Fair and requested a catalog.",
    }
    created = client.post(
        f"/discovery/organizations/{client.acme_id}/leads",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json=payload,
    )
    duplicate = client.post(
        f"/discovery/organizations/{client.acme_id}/leads",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json=payload,
    )
    cross_tenant = client.post(
        f"/discovery/organizations/{client.globex_id}/leads",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json=payload,
    )
    lead_id = created.json()["id"]
    task = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/follow-up-tasks",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "title": "Prepare FOB quotation",
            "task_type": "quote",
            "quote_status": "preparing_quote",
            "due_at": "2026-08-05T09:00:00Z",
        },
    )
    listed_tasks = client.get(
        f"/discovery/organizations/{client.acme_id}/follow-up-tasks?status_filter=open",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    detail_with_task = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    completed_task = client.post(
        f"/discovery/organizations/{client.acme_id}/follow-up-tasks/{task.json()['id']}/complete",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    listed_done_tasks = client.get(
        f"/discovery/organizations/{client.acme_id}/follow-up-tasks?status_filter=done",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    follow_ups_after_task = client.get(
        f"/discovery/organizations/{client.acme_id}/follow-ups",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    quote = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/quote-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "title": "FOB sample quotation",
            "currency": "USD",
            "incoterm": "FOB",
            "valid_until": "2026-08-20T00:00:00Z",
            "line_items": [
                {
                    "item_name": "LED floodlight 200W",
                    "quantity": 500,
                    "unit_price": 12.5,
                    "unit": "pcs",
                    "notes": "Sample batch",
                }
            ],
            "notes": "Manual quotation draft. Review before sending.",
        },
    )
    updated_quote = client.patch(
        f"/discovery/organizations/{client.acme_id}/quote-drafts/{quote.json()['id']}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "title": "FOB sample quotation v2",
            "currency": "USD",
            "incoterm": "FOB",
            "valid_until": "2026-08-20T00:00:00Z",
            "line_items": [
                {
                    "item_name": "LED floodlight 200W",
                    "quantity": 500,
                    "unit_price": 11.8,
                    "unit": "pcs",
                    "notes": "Discounted sample batch",
                }
            ],
            "notes": "Updated after margin review.",
        },
    )
    sent_quote = client.post(
        f"/discovery/organizations/{client.acme_id}/quote-drafts/{quote.json()['id']}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    listed_quotes = client.get(
        f"/discovery/organizations/{client.acme_id}/quote-drafts?status_filter=sent",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    detail_with_quote = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    follow_ups_after_quote = client.get(
        f"/discovery/organizations/{client.acme_id}/follow-ups",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    deleted = client.delete(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    missing_after_delete = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert created.status_code == 201
    assert created.json()["website"] == "https://manual-import.example"
    assert created.json()["bucket"] == "needs_enrichment"
    assert created.json()["status"] == "to_contact"
    assert created.json()["evidence"][0]["signal_name"] == "manual_entry"
    assert duplicate.status_code == 409
    assert cross_tenant.status_code == 403
    assert task.status_code == 201
    assert task.json()["quote_status"] == "preparing_quote"
    assert task.json()["status"] == "open"
    assert listed_tasks.status_code == 200
    assert listed_tasks.json()[0]["lead_company_name"] == "Manual Import GmbH"
    assert detail_with_task.status_code == 200
    assert detail_with_task.json()["status"] == "quoting"
    assert detail_with_task.json()["follow_up_tasks"][0]["title"] == "Prepare FOB quotation"
    assert completed_task.status_code == 200
    assert completed_task.json()["status"] == "done"
    assert listed_done_tasks.json()[0]["id"] == task.json()["id"]
    assert follow_ups_after_task.json()[0]["activity_type"] == "task_done"
    assert quote.status_code == 201
    assert quote.json()["status"] == "draft"
    assert quote.json()["total_amount"] == 6250
    assert updated_quote.status_code == 200
    assert updated_quote.json()["title"] == "FOB sample quotation v2"
    assert updated_quote.json()["total_amount"] == 5900
    assert sent_quote.status_code == 200
    assert sent_quote.json()["status"] == "sent"
    assert listed_quotes.json()[0]["lead_company_name"] == "Manual Import GmbH"
    assert detail_with_quote.json()["quote_drafts"][0]["status"] == "sent"
    assert follow_ups_after_quote.json()[0]["activity_type"] == "quote_sent"
    assert "USD 5900.00" in follow_ups_after_quote.json()[0]["content"]
    assert deleted.status_code == 204
    assert missing_after_delete.status_code == 404


def test_website_inquiry_api_accepts_public_submission_and_converts_to_customer() -> None:
    client, _ = configured_client()
    with client.app.state.session_factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        other_product_line = ProductLine(organization_id=client.globex_id, name="Other")  # type: ignore[attr-defined]
        session.add_all([product_line, other_product_line])
        session.flush()
        product_item = ProductItem(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            product_line_id=product_line.id,
            name="LED Floodlight 200W",
            sku="FL-200W",
            specs=["200W", "IP66"],
            is_published=True,
        )
        session.add(product_item)
        session.flush()
        product_line_id = product_line.id
        product_item_id = product_item.id
        other_product_line_id = other_product_line.id

    payload = {
        "product_line_id": product_line_id,
        "product_item_id": product_item_id,
        "company_name": "Inquiry Buyer Ltd",
        "contact_name": "Mina Lee",
        "email": "mina@buyer.example",
        "phone": "+82 10 5555 1234",
        "target_market": "Korea",
        "message": "Need quotation for 300 sample units and lead time.",
        "source_url": "https://brand.example/products/lighting",
    }
    submitted = client.post(
        f"/discovery/public/organizations/{client.acme_id}/website-inquiries",  # type: ignore[attr-defined]
        json=payload,
    )
    invalid_product = client.post(
        f"/discovery/public/organizations/{client.acme_id}/website-inquiries",  # type: ignore[attr-defined]
        json={**payload, "product_line_id": other_product_line_id},
    )
    listed = client.get(
        f"/discovery/organizations/{client.acme_id}/website-inquiries?status_filter=new",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    cross_tenant = client.get(
        f"/discovery/organizations/{client.globex_id}/website-inquiries",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    inquiry_id = submitted.json()["id"]
    converted = client.post(
        f"/discovery/organizations/{client.acme_id}/website-inquiries/{inquiry_id}/convert",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    duplicate_convert = client.post(
        f"/discovery/organizations/{client.acme_id}/website-inquiries/{inquiry_id}/convert",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert submitted.status_code == 201
    assert submitted.json()["status"] == WebsiteInquiryStatus.NEW
    assert submitted.json()["product_item_id"] == product_item_id
    assert submitted.json()["product_item_name"] == "LED Floodlight 200W"
    assert submitted.json()["lead_id"] is None
    assert invalid_product.status_code == 404
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == inquiry_id
    assert cross_tenant.status_code == 403
    assert converted.status_code == 200
    assert converted.json()["inquiry"]["status"] == WebsiteInquiryStatus.CONVERTED
    assert converted.json()["inquiry"]["lead_id"] == converted.json()["lead"]["id"]
    assert converted.json()["lead"]["status"] == LeadStatus.INTERESTED
    assert converted.json()["lead"]["website"] == "https://buyer.example"
    assert converted.json()["lead"]["contacts"][0]["email"] == "mina@buyer.example"
    assert converted.json()["lead"]["contacts"][0]["is_primary"] is True
    assert converted.json()["lead"]["follow_ups"][0]["activity_type"] == "inquiry"
    assert "LED Floodlight 200W" in converted.json()["lead"]["follow_ups"][0]["content"]
    assert "300 sample units" in converted.json()["lead"]["follow_ups"][0]["content"]
    assert duplicate_convert.status_code == 409


def test_customer_detail_routes_update_status_and_record_follow_up() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="manual_crm",
            agent_version="1.0.0",
            input_json={},
            idempotency_key="customer-detail-route-run",
        )
        session.add(workflow_run)
        session.flush()
        lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="Follow Up GmbH",
            website="https://follow-up.example",
            canonical_domain="follow-up.example",
            target_market="Germany",
            buyer_profile="distributor",
            score=70,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            reasons=["人工添加客户"],
            missing_signals=["联系人待补充"],
        )
        session.add(lead)
        session.flush()
        lead_id = lead.id

    updated = client.patch(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "status": "interested",
            "notes": "Needs FOB quote for 500 units.",
            "owner_user_id": None,
        },
    )
    contact = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/contacts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "name": "Anna Weber",
            "title": "Purchasing Manager",
            "email": "anna@follow-up.example",
            "phone": "+49 30 123456",
            "linkedin_url": "https://linkedin.com/in/anna-weber",
            "whatsapp": "+49 171 123456",
            "social_profiles": [
                {"platform": "Instagram", "url": "https://instagram.com/followup"},
                {"platform": "Instagram", "url": "https://instagram.com/followup/"},
            ],
            "source_url": "https://follow-up.example/contact",
            "is_primary": True,
        },
    )
    discovered_contacts = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/contacts/discover",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"limit": 2},
    )
    verified_contact = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/contacts/{contact.json()['id']}/verify-email",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    email_draft = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/email-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"contact_id": contact.json()["id"]},
    )
    email_draft_id = email_draft.json()["id"]
    listed_drafts = client.get(
        f"/discovery/organizations/{client.acme_id}/email-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    edited_draft = client.patch(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{email_draft_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "subject": "Edited subject",
            "body": (
                "Dear Anna Weber, your LED retail fixtures match our 0-10V dimmable drivers. "
                "We can share tested specifications for your next range review. "
                "Would a 15-minute call next week be useful?"
            ),
        },
    )
    approved_draft = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{email_draft_id}/review",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"action": "approve"},
    )
    sent_draft = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{email_draft_id}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    duplicate_send = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{email_draft_id}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    updated_sent_contact_email = client.patch(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{email_draft_id}/contact-email",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"email": "new-buyer@follow-up.example"},
    )
    sent_detail = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    organization_follow_ups = client.get(
        f"/discovery/organizations/{client.acme_id}/follow-ups",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    follow_up = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/follow-ups",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "activity_type": "email",
            "content": "Sent catalog and asked for target quantity.",
            "next_follow_up_at": "2026-08-03T09:00:00Z",
        },
    )
    detail = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    cross_tenant = client.get(
        f"/discovery/organizations/{client.globex_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert updated.status_code == 200
    assert updated.json()["status"] == LeadStatus.INTERESTED
    assert updated.json()["notes"] == "Needs FOB quote for 500 units."
    assert contact.status_code == 201
    assert contact.json()["social_profiles"] == [
        {"platform": "Instagram", "url": "https://instagram.com/followup"}
    ]
    assert contact.json()["source_url"] == "https://follow-up.example/contact"
    assert contact.json()["name"] == "Anna Weber"
    assert contact.json()["is_primary"] is True
    assert discovered_contacts.status_code == 201
    assert client.contact_discovery_connector.requests == [("follow-up.example", 2)]  # type: ignore[attr-defined]
    assert [item["email"] for item in discovered_contacts.json()] == ["buyer@follow-up.example"]
    assert "Hunter confidence 77" in discovered_contacts.json()[0]["title"]
    assert verified_contact.status_code == 200
    assert verified_contact.json()["email_verification_provider"] == "ZeroBounce"
    assert verified_contact.json()["email_verification_status"] == "valid"
    assert verified_contact.json()["email_verified_at"] is not None
    assert client.email_verification_connector.requests == ["anna@follow-up.example"]  # type: ignore[attr-defined]
    assert email_draft.status_code == 201
    assert email_draft.json()["status"] == EmailDraftStatus.PENDING_APPROVAL
    assert email_draft.json()["contact_email"] == "anna@follow-up.example"
    assert email_draft.json()["send_risk_level"] == "safe"
    assert email_draft.json()["send_blocked"] is False
    assert "Follow Up GmbH" in email_draft.json()["body"]
    assert listed_drafts.status_code == 200
    assert listed_drafts.json()[0]["id"] == email_draft_id
    assert edited_draft.status_code == 200
    assert edited_draft.json()["subject"] == "Edited subject"
    assert approved_draft.status_code == 200
    assert approved_draft.json()["status"] == EmailDraftStatus.READY_TO_SEND
    assert approved_draft.json()["reviewed_by_user_id"] == client.admin_id  # type: ignore[attr-defined]
    assert sent_draft.status_code == 200
    assert sent_draft.json()["status"] == EmailDraftStatus.SENT
    assert sent_draft.json()["sent_by_user_id"] == client.member_id  # type: ignore[attr-defined]
    assert sent_draft.json()["sent_at"] is not None
    assert sent_draft.json()["provider_message_id"] == "fake-provider-message-id"
    assert duplicate_send.status_code == 200
    assert duplicate_send.json()["status"] == EmailDraftStatus.SENT
    assert duplicate_send.json()["provider_message_id"] == "fake-provider-message-id"
    assert updated_sent_contact_email.status_code == 200
    assert updated_sent_contact_email.json()["contact_email"] == "anna@follow-up.example"
    assert updated_sent_contact_email.json()["current_contact_email"] == "new-buyer@follow-up.example"
    assert updated_sent_contact_email.json()["contact_email_verification_status"] == ""
    assert len(client.email_connector.sent_messages) == 1  # type: ignore[attr-defined]
    sent_message, idempotency_key = client.email_connector.sent_messages[0]  # type: ignore[attr-defined]
    assert sent_message.recipients == ["anna@follow-up.example"]
    assert sent_message.subject == "Edited subject"
    assert sent_message.body == (
        "Dear Anna Weber, your LED retail fixtures match our 0-10V dimmable drivers. "
        "We can share tested specifications for your next range review. "
        "Would a 15-minute call next week be useful?"
    )
    assert idempotency_key == f"email-draft:{email_draft_id}"
    assert sent_detail.json()["status"] == LeadStatus.CONTACTED
    assert any(
        record["activity_type"] == "email_sent"
        and "Edited subject" in record["content"]
        and record["next_follow_up_at"] is not None
        for record in sent_detail.json()["follow_ups"]
    )
    assert any(record["activity_type"] == "email_verified" for record in sent_detail.json()["follow_ups"])
    assert organization_follow_ups.status_code == 200
    assert organization_follow_ups.json()[0]["lead_company_name"] == "Follow Up GmbH"
    assert organization_follow_ups.json()[0]["activity_type"] == "email_sent"
    assert organization_follow_ups.json()[0]["lead_status"] == LeadStatus.CONTACTED
    assert follow_up.status_code == 201
    assert detail.status_code == 200
    assert [item["email"] for item in detail.json()["contacts"]] == [
        "new-buyer@follow-up.example",
        "buyer@follow-up.example",
    ]
    assert detail.json()["follow_ups"][0]["activity_type"] == "email"
    assert detail.json()["follow_ups"][0]["content"] == "Sent catalog and asked for target quantity."
    assert cross_tenant.status_code == 403

    deleted_contact = client.delete(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/contacts/{contact.json()['id']}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    detail_after_delete = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    with factory() as session:
        deleted = session.get(CRMContact, contact.json()["id"])

    assert deleted_contact.status_code == 204
    assert [item["email"] for item in detail_after_delete.json()["contacts"]] == [
        "buyer@follow-up.example"
    ]
    assert deleted is None


def test_daily_contact_discovery_only_scans_leads_found_on_the_selected_local_date() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="customer_discovery_agent",
            agent_version="1.0.0",
            input_json={},
            idempotency_key="daily-contact-discovery-run",
        )
        session.add(workflow_run)
        session.flush()
        session.add_all(
            [
                Lead(
                    organization_id=client.acme_id,  # type: ignore[attr-defined]
                    workflow_run_id=workflow_run.id,
                    product_line_id=product_line.id,
                    company_name="Today Buyer GmbH",
                    website="https://follow-up.example",
                    canonical_domain="follow-up.example",
                    target_market="Germany",
                    buyer_profile="distributor",
                    score=82,
                    bucket=LeadBucket.PRIORITY_RECOMMENDATION,
                    reasons=["product match"],
                    missing_signals=["contact"],
                    last_discovered_at=datetime(2026, 8, 13, 1, tzinfo=timezone.utc),
                ),
                Lead(
                    organization_id=client.acme_id,  # type: ignore[attr-defined]
                    workflow_run_id=workflow_run.id,
                    product_line_id=product_line.id,
                    company_name="Map Only Buyer",
                    website="https://www.openstreetmap.org/node/123",
                    canonical_domain="osm:node:123",
                    target_market="Germany",
                    buyer_profile="distributor",
                    score=64,
                    bucket=LeadBucket.NEEDS_ENRICHMENT,
                    reasons=["map result"],
                    missing_signals=["website"],
                    last_discovered_at=datetime(2026, 8, 13, 2, tzinfo=timezone.utc),
                ),
                Lead(
                    organization_id=client.acme_id,  # type: ignore[attr-defined]
                    workflow_run_id=workflow_run.id,
                    product_line_id=product_line.id,
                    company_name="Yesterday Buyer GmbH",
                    website="https://yesterday.example",
                    canonical_domain="yesterday.example",
                    target_market="Germany",
                    buyer_profile="distributor",
                    score=75,
                    bucket=LeadBucket.NEEDS_ENRICHMENT,
                    reasons=["product match"],
                    missing_signals=["contact"],
                    last_discovered_at=datetime(2026, 8, 12, 10, tzinfo=timezone.utc),
                ),
            ]
        )

    response = client.post(
        f"/discovery/organizations/{client.acme_id}/contacts/discover-daily",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "discovery_date": "2026-08-13",
            "timezone": "Asia/Shanghai",
            "lead_limit": 50,
            "contacts_per_lead": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["lead_count"] == 2
    assert response.json()["processed_count"] == 1
    assert response.json()["contacts_found"] == 2
    assert response.json()["skipped_count"] == 1
    assert response.json()["failed_count"] == 0
    assert [item["company_name"] for item in response.json()["items"]] == [
        "Map Only Buyer",
        "Today Buyer GmbH",
    ]
    assert client.contact_discovery_connector.requests == [("follow-up.example", 2)]  # type: ignore[attr-defined]
    with factory() as session:
        contacts = list(session.scalars(select(CRMContact).order_by(CRMContact.email)))
        assert [contact.email for contact in contacts] == [
            "anna@follow-up.example",
            "buyer@follow-up.example",
        ]


def test_batch_contact_discovery_persists_contact_status_summary() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="customer_discovery_agent",
            agent_version="1.1.0",
            input_json={},
            idempotency_key="batch-contact-discovery-run",
        )
        session.add(workflow_run)
        session.flush()
        website_lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="Website Buyer GmbH",
            website="https://follow-up.example",
            canonical_domain="follow-up.example",
            target_market="Germany",
            score=80,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
        )
        map_lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="Map Only Buyer",
            website="https://www.openstreetmap.org/node/456",
            canonical_domain="osm:node:456",
            target_market="Germany",
            score=60,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
        )
        session.add_all([website_lead, map_lead])
        session.flush()
        website_lead_id = website_lead.id
        map_lead_id = map_lead.id

    response = client.post(
        f"/discovery/organizations/{client.acme_id}/contacts/discover-batch",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"lead_ids": [website_lead_id, map_lead_id], "contacts_per_lead": 2},
    )
    listed = client.get(
        f"/discovery/organizations/{client.acme_id}/leads",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    items = {item["lead_id"]: item for item in response.json()["items"]}
    assert items[website_lead_id]["status"] == "has_email"
    assert items[website_lead_id]["email_count"] == 2
    assert items[website_lead_id]["checked_email_count"] == 2
    assert items[website_lead_id]["phone_count"] == 1
    assert items[website_lead_id]["social_count"] == 1
    assert items[map_lead_id]["status"] == "needs_review"
    persisted = {item["id"]: item for item in listed.json()}
    assert persisted[website_lead_id]["contact_discovery_status"] == "has_email"
    assert persisted[website_lead_id]["contact_discovered_at"]
    assert persisted[map_lead_id]["contact_discovery_status"] == "needs_review"
    assert set(client.email_verification_connector.requests) == {  # type: ignore[attr-defined]
        "anna@follow-up.example",
        "buyer@follow-up.example",
    }


def test_batch_contact_discovery_limits_each_request_to_five_leads() -> None:
    client, _ = configured_client()

    response = client.post(
        f"/discovery/organizations/{client.acme_id}/contacts/discover-batch",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"lead_ids": [str(index) for index in range(6)]},
    )

    assert response.status_code == 422

def test_email_send_blocks_invalid_verified_contact() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="manual_crm",
            agent_version="1.0.0",
            input_json={},
            idempotency_key="blocked-email-route-run",
        )
        session.add(workflow_run)
        session.flush()
        lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="Blocked Email GmbH",
            website="https://blocked-email.example",
            canonical_domain="blocked-email.example",
            target_market="Germany",
            buyer_profile="distributor",
            score=70,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            reasons=["manual test lead"],
            missing_signals=[],
        )
        session.add(lead)
        session.flush()
        contact = CRMContact(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            lead_id=lead.id,
            name="Invalid Buyer",
            title="Purchasing",
            email="invalid@blocked-email.example",
            email_verification_provider="ZeroBounce",
            email_verification_status="invalid",
            is_primary=True,
        )
        session.add(contact)
        session.flush()
        lead_id = lead.id
        contact_id = contact.id

    draft = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/email-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"contact_id": contact_id},
    )
    edited = client.patch(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft.json()['id']}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "subject": "Dimmable LED drivers for your lighting range",
            "body": (
                "Dear Invalid Buyer, your lighting fixtures match our dimmable LED drivers. "
                "Would a 15-minute call next week be useful?"
            ),
        },
    )
    approved = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft.json()['id']}/review",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"action": "approve"},
    )
    blocked = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft.json()['id']}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert draft.status_code == 201
    assert draft.json()["send_blocked"] is True
    assert draft.json()["send_risk_level"] == "blocked"
    assert edited.status_code == 200
    assert edited.json()["quality"]["passed"] is True
    assert approved.status_code == 200
    assert approved.json()["status"] == EmailDraftStatus.READY_TO_SEND
    assert approved.json()["send_blocked"] is True
    assert blocked.status_code == 409
    assert "email verification blocks sending" in blocked.json()["detail"]
    assert client.email_connector.sent_messages == []  # type: ignore[attr-defined]


def _seed_email_draft_lead(client, factory, *, company_name, contact_name, email, run_key):
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="manual_crm",
            agent_version="1.0.0",
            input_json={},
            idempotency_key=run_key,
        )
        session.add(workflow_run)
        session.flush()
        domain = company_name.lower().replace(" ", "-")
        lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name=company_name,
            website=f"https://{domain}.example",
            canonical_domain=f"{domain}.example",
            target_market="Germany",
            buyer_profile="distributor",
            score=70,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            reasons=["manual test lead"],
            missing_signals=[],
        )
        session.add(lead)
        session.flush()
        contact = CRMContact(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            lead_id=lead.id,
            name=contact_name,
            title="Purchasing",
            email=email,
            email_verification_provider="ZeroBounce",
            email_verification_status="valid",
            is_primary=True,
        )
        session.add(contact)
        session.flush()
        return lead.id, contact.id


def test_unapproved_draft_never_reaches_email_connector() -> None:
    client, factory = configured_client()
    lead_id, contact_id = _seed_email_draft_lead(
        client,
        factory,
        company_name="Unapproved GmbH",
        contact_name="Buyer",
        email="buyer@unapproved.example",
        run_key="unapproved-send-route-run",
    )

    draft = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/email-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"contact_id": contact_id},
    )
    blocked = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft.json()['id']}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert draft.status_code == 201
    assert draft.json()["status"] == EmailDraftStatus.PENDING_APPROVAL
    assert blocked.status_code == 409
    assert "only ready-to-send drafts can be sent" in blocked.json()["detail"]
    assert client.email_connector.sent_messages == []  # type: ignore[attr-defined]


def test_review_approve_rejects_generic_draft_with_repair_codes() -> None:
    client, factory = configured_client()
    lead_id, contact_id = _seed_email_draft_lead(
        client,
        factory,
        company_name="Generic Draft GmbH",
        contact_name="Buyer",
        email="buyer@generic-draft.example",
        run_key="generic-draft-route-run",
    )

    draft = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/email-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"contact_id": contact_id},
    )
    edited = client.patch(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft.json()['id']}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"subject": "Hello", "body": "We offer good products. Please reply."},
    )
    approved = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft.json()['id']}/review",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"action": "approve"},
    )

    assert edited.status_code == 200
    assert edited.json()["quality"]["passed"] is False
    assert {issue["code"] for issue in edited.json()["quality"]["issues"]} >= {
        "missing_product_evidence",
        "missing_personalization",
    }
    assert approved.status_code == 409
    detail = approved.json()["detail"]
    assert isinstance(detail, list)
    codes = {issue["code"] for issue in detail}
    assert {"missing_product_evidence", "missing_personalization"} <= codes
    assert all("suggestion" in issue for issue in detail)


def test_resend_short_circuits_when_draft_already_sent() -> None:
    client, factory = configured_client()
    lead_id, contact_id = _seed_email_draft_lead(
        client,
        factory,
        company_name="Idempotent Send GmbH",
        contact_name="Buyer",
        email="buyer@idempotent-send.example",
        run_key="idempotent-send-route-run",
    )

    draft = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/email-drafts",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"contact_id": contact_id},
    )
    draft_id = draft.json()["id"]
    client.patch(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "subject": "Dimmable LED drivers for your lighting range",
            "body": (
                "Dear Buyer, your lighting fixtures match our dimmable LED drivers. "
                "Would a 15-minute call next week be useful?"
            ),
        },
    )
    client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft_id}/review",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"action": "approve"},
    )
    first_send = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft_id}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    second_send = client.post(
        f"/discovery/organizations/{client.acme_id}/email-drafts/{draft_id}/send",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert first_send.status_code == 200
    assert first_send.json()["status"] == EmailDraftStatus.SENT
    assert second_send.status_code == 200
    assert second_send.json()["status"] == EmailDraftStatus.SENT
    assert second_send.json()["provider_message_id"] == first_send.json()["provider_message_id"]
    assert len(client.email_connector.sent_messages) == 1  # type: ignore[attr-defined]


def test_reply_follow_up_marks_customer_interested() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        session.add(product_line)
        session.flush()
        workflow_run = WorkflowRun(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            agent_id="manual_crm",
            agent_version="1.0.0",
            input_json={},
            idempotency_key="reply-follow-up-route-run",
        )
        session.add(workflow_run)
        session.flush()
        lead = Lead(
            organization_id=client.acme_id,  # type: ignore[attr-defined]
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="Reply GmbH",
            website="https://reply.example",
            canonical_domain="reply.example",
            target_market="Germany",
            buyer_profile="distributor",
            score=70,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            status=LeadStatus.CONTACTED,
            reasons=["人工添加客户"],
            missing_signals=["联系人待补充"],
        )
        session.add(lead)
        session.flush()
        lead_id = lead.id

    reply = client.post(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/follow-ups",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={
            "activity_type": "reply",
            "content": "Customer asked for a 500-unit quote.",
        },
    )
    detail = client.get(
        f"/discovery/organizations/{client.acme_id}/leads/{lead_id}/detail",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    inbox = client.get(
        f"/discovery/organizations/{client.acme_id}/follow-ups",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert reply.status_code == 201
    assert reply.json()["activity_type"] == "reply"
    assert detail.json()["status"] == LeadStatus.INTERESTED
    assert inbox.json()[0]["lead_company_name"] == "Reply GmbH"
    assert inbox.json()[0]["lead_status"] == LeadStatus.INTERESTED


def test_register_creates_admin_and_login_issues_a_bearer_token() -> None:
    client, factory = configured_client()
    payload = {
        "organization_name": "Nova Export",
        "display_name": "Mia Chen",
        "email": "mia@example.com",
        "password": "a-long-local-password",
    }
    registered = client.post("/platform/auth/register", json=payload)
    logged_in = client.post(
        "/platform/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    rejected = client.post(
        "/platform/auth/login", json={"email": payload["email"], "password": "wrong-password"}
    )

    assert registered.status_code == 201
    assert logged_in.status_code == 200
    assert logged_in.json()["organization_id"] == registered.json()["organization_id"]
    assert logged_in.json()["access_token"]
    assert rejected.status_code == 401


def test_frontend_origin_can_post_to_auth_routes() -> None:
    client, _ = configured_client()

    response = client.options(
        "/platform/auth/login",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
