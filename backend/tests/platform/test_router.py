import time

from cryptography.fernet import Fernet

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from app.platform.models import ConnectorCredential, MembershipRole, Organization, ProductLine, User, UserMembership
from app.shared.config import Settings
from app.shared.db import Base
from app.shared.security import PrincipalTokenCodec
from app.workflow.models import WorkflowRun


APP_SECRET = "a-local-test-secret-that-is-long-enough"


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
    client = TestClient(create_app(session_factory=factory, settings=settings))
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
    listed = client.get(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    cross_tenant = client.get(
        f"/platform/organizations/{client.globex_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["product_keywords"] == ["LED floodlight", "warehouse lighting"]
    assert supplier.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["suppliers"] == ["NOVA Lighting Factory"]
    assert cross_tenant.status_code == 403


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
    assert deleted.status_code == 204
    assert missing_after_delete.status_code == 404


def test_website_inquiry_api_accepts_public_submission_and_converts_to_customer() -> None:
    client, _ = configured_client()
    with client.app.state.session_factory.begin() as session:
        product_line = ProductLine(organization_id=client.acme_id, name="Lighting")  # type: ignore[attr-defined]
        other_product_line = ProductLine(organization_id=client.globex_id, name="Other")  # type: ignore[attr-defined]
        session.add_all([product_line, other_product_line])
        session.flush()
        product_line_id = product_line.id
        other_product_line_id = other_product_line.id

    payload = {
        "product_line_id": product_line_id,
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
            "is_primary": True,
        },
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
            "body": "Edited body with reviewer changes.",
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
    assert contact.json()["name"] == "Anna Weber"
    assert contact.json()["is_primary"] is True
    assert email_draft.status_code == 201
    assert email_draft.json()["status"] == EmailDraftStatus.PENDING_APPROVAL
    assert email_draft.json()["contact_email"] == "anna@follow-up.example"
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
    assert sent_detail.json()["status"] == LeadStatus.CONTACTED
    assert any(
        record["activity_type"] == "email_sent"
        and "Edited subject" in record["content"]
        and record["next_follow_up_at"] is not None
        for record in sent_detail.json()["follow_ups"]
    )
    assert organization_follow_ups.status_code == 200
    assert organization_follow_ups.json()[0]["lead_company_name"] == "Follow Up GmbH"
    assert organization_follow_ups.json()[0]["activity_type"] == "email_sent"
    assert organization_follow_ups.json()[0]["lead_status"] == LeadStatus.CONTACTED
    assert follow_up.status_code == 201
    assert detail.status_code == 200
    assert detail.json()["contacts"][0]["email"] == "anna@follow-up.example"
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
    assert detail_after_delete.json()["contacts"] == []
    assert deleted is None


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
