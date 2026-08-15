from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.connectors.email.imap import ImapError, InboundEmailRecord
from app.crm.inbox import InboxService, ReplyIntent, classify_reply
from app.crm.models import (
    CRMContact,
    FollowUpRecord,
    FollowUpTask,
    InboundMessage,
    Lead,
    LeadBucket,
    MailboxCursor,
)
from app.main import create_app
from app.platform.models import MembershipRole, Organization, ProductLine, User, UserMembership
from app.shared.config import Settings
from app.shared.db import Base
from app.shared.security import PrincipalTokenCodec
from app.workflow.models import WorkflowRun

APP_SECRET = "a-local-test-secret-that-is-long-enough"


class FakeImapConnector:
    connector_id = "fake-imap"
    version = "v1"

    def __init__(self, messages: dict[int, InboundEmailRecord] | None = None) -> None:
        self.messages: dict[int, InboundEmailRecord] = dict(messages or {})

    def list_since_uid(self, mailbox: str = "INBOX", since_uid: int = 0) -> list[InboundEmailRecord]:
        return [
            record for uid, record in sorted(self.messages.items()) if uid > since_uid
        ]

    def latest_uid(self, mailbox: str = "INBOX") -> int | None:
        return max(self.messages) if self.messages else None


def make_record(
    provider_message_id: str,
    subject: str,
    body: str,
    *,
    sender_email: str = "buyer@example.com",
    sender_name: str = "Buyer",
) -> InboundEmailRecord:
    return InboundEmailRecord(
        provider_message_id=provider_message_id,
        thread_id=provider_message_id,
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        body_text=body,
        received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        attachments_count=0,
    )


def _make_lead(
    session,
    organization: Organization,
    *,
    domain: str = "example.com",
    contact_email: str = "buyer@example.com",
) -> tuple[Lead, CRMContact]:
    product_line = ProductLine(organization_id=organization.id, name="LED Lighting")
    workflow_run = WorkflowRun(
        organization_id=organization.id,
        agent_id="inbox-test",
        agent_version="1.0.0",
        input_json={},
        idempotency_key=f"inbox-{domain}",
    )
    session.add_all([product_line, workflow_run])
    session.flush()
    lead = Lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        company_name="Example Buyer GmbH",
        website=f"https://{domain}",
        canonical_domain=domain,
        target_market="Germany",
        score=70,
        bucket=LeadBucket.NEEDS_ENRICHMENT,
    )
    session.add(lead)
    session.flush()
    contact = CRMContact(
        organization_id=organization.id,
        lead_id=lead.id,
        name="Buyer",
        email=contact_email,
        is_primary=True,
    )
    session.add(contact)
    session.flush()
    return lead, contact


def test_sync_reply_creates_analysis_follow_up_and_timeline(session, organizations) -> None:
    organization = organizations["acme"]
    lead, _ = _make_lead(session, organization)
    imap = FakeImapConnector(
        {1: make_record("msg-1", "Re: Offer", "We are very interested in your LED products.")}
    )

    synced = InboxService(session, imap).sync_organization_mailbox(organization.id)

    assert synced == 1
    message = session.scalar(
        select(InboundMessage).where(InboundMessage.organization_id == organization.id)
    )
    assert message is not None
    assert message.intent in {intent.value for intent in ReplyIntent}
    assert message.follow_up_task_id is not None
    assert message.analysis_rationale
    assert message.suggested_reply
    timeline = session.scalars(
        select(FollowUpRecord).where(FollowUpRecord.lead_id == lead.id)
    ).all()
    assert any(record.activity_type == "reply_analyzed" for record in timeline)


def test_sync_is_idempotent(session, organizations) -> None:
    organization = organizations["acme"]
    _make_lead(session, organization)
    imap = FakeImapConnector(
        {1: make_record("msg-1", "Re: Offer", "We are interested in your products.")}
    )
    service = InboxService(session, imap)

    assert service.sync_organization_mailbox(organization.id) == 1
    # Simulate re-delivery of the same UID by rewinding the cursor.
    cursor = session.get(MailboxCursor, (organization.id, "INBOX"))
    assert cursor is not None
    cursor.last_uid = 0
    session.commit()

    assert service.sync_organization_mailbox(organization.id) == 0
    assert session.scalar(select(func.count()).select_from(InboundMessage)) == 1
    assert session.scalar(select(func.count()).select_from(FollowUpTask)) == 1


def test_cursor_advances_only_on_success(session, organizations) -> None:
    organization = organizations["acme"]
    _make_lead(session, organization)
    imap = FakeImapConnector(
        {1: make_record("msg-1", "Re: Offer", "We are interested in your products.")}
    )
    InboxService(session, imap).sync_organization_mailbox(organization.id)

    cursor = session.get(MailboxCursor, (organization.id, "INBOX"))
    assert cursor is not None
    assert cursor.last_uid == 1

    class FailingImap:
        def latest_uid(self, mailbox: str = "INBOX") -> int:
            return 2

        def list_since_uid(self, mailbox: str = "INBOX", since_uid: int = 0):
            raise ImapError("boom")

    with pytest.raises(ImapError):
        InboxService(session, FailingImap()).sync_organization_mailbox(organization.id)

    cursor = session.get(MailboxCursor, (organization.id, "INBOX"))
    assert cursor is not None
    assert cursor.last_uid == 1


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        ("Re: hello", "We are very interested in your products and would like a catalog.", "interested"),
        ("Re: hello", "What is your MOQ and lead time?", "question"),
        ("Re: hello", "We are not ready now, please contact us next quarter.", "not_now"),
        ("Re: hello", "We are not interested, please do not contact us again.", "not_interested"),
        ("Out of Office", "I am currently away from the office.", "out_of_office"),
        ("Re: hello", "Thank you for your email.", "other"),
    ],
)
def test_classify_reply_rules(subject: str, body: str, expected: str) -> None:
    result = classify_reply(subject, body)

    assert result.intent == expected
    assert result.confidence > 0
    assert result.rationale
    assert result.suggested_reply


def test_company_association_by_canonical_email(session, organizations) -> None:
    organization = organizations["acme"]
    lead, _ = _make_lead(
        session, organization, domain="buyer.example", contact_email="anna@buyer.example"
    )
    imap = FakeImapConnector(
        {
            1: make_record(
                "msg-1", "Re: Offer", "We are interested.", sender_email="anna@buyer.example"
            )
        }
    )

    InboxService(session, imap).sync_organization_mailbox(organization.id)

    message = session.scalar(select(InboundMessage))
    assert message is not None
    assert message.follow_up_task_id is not None
    task = session.get(FollowUpTask, message.follow_up_task_id)
    assert task is not None
    assert task.lead_id == lead.id


def bearer_headers(user_id: str) -> dict[str, str]:
    token = PrincipalTokenCodec(APP_SECRET).issue(user_id, expires_at=int(time.time()) + 3_600)
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
    member = User(email="member@acme.example", display_name="Acme Member")
    admin = User(email="admin@acme.example", display_name="Acme Admin")
    with factory.begin() as session:
        session.add_all([acme, member, admin])
        session.flush()
        session.add_all(
            [
                UserMembership(user_id=member.id, organization_id=acme.id, role=MembershipRole.MEMBER),
                UserMembership(user_id=admin.id, organization_id=acme.id, role=MembershipRole.ADMIN),
            ]
        )
    settings = Settings(
        app_secret=APP_SECRET,
        credential_encryption_key=Fernet.generate_key().decode(),
        database_url="sqlite://",
        redis_url="redis://redis:6379/0",
        s3_endpoint="http://minio:9000",
    )
    client = TestClient(
        create_app(session_factory=factory, settings=settings, imap_connector=FakeImapConnector())
    )
    client.acme_id = acme.id  # type: ignore[attr-defined]
    client.member_id = member.id  # type: ignore[attr-defined]
    client.admin_id = admin.id  # type: ignore[attr-defined]
    return client, factory


def test_router_authz_and_intent_filter() -> None:
    client, factory = configured_client()
    with factory.begin() as session:
        session.add_all(
            [
                InboundMessage(
                    organization_id=client.acme_id,  # type: ignore[attr-defined]
                    provider_message_id="a",
                    sender_email="a@example.com",
                    subject="A",
                    body_text="",
                    received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    intent="interested",
                ),
                InboundMessage(
                    organization_id=client.acme_id,  # type: ignore[attr-defined]
                    provider_message_id="b",
                    sender_email="b@example.com",
                    subject="B",
                    body_text="",
                    received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    intent="question",
                ),
            ]
        )

    listed = client.get(
        f"/organizations/{client.acme_id}/inbox",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    filtered = client.get(
        f"/organizations/{client.acme_id}/inbox?intent=interested",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert len(body) == 1
    assert body[0]["intent"] == "interested"

    forbidden = client.post(
        f"/organizations/{client.acme_id}/inbox/sync",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    assert forbidden.status_code == 403

    synced = client.post(
        f"/organizations/{client.acme_id}/inbox/sync",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
    )
    assert synced.status_code == 200
    assert synced.json()["synced"] == 0
