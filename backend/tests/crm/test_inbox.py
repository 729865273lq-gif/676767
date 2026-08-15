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
from app.crm.inbox import InboxService, ReplyIntent, classify_reply, poll_organization_ids
from app.crm.models import (
    CRMContact,
    FollowUpRecord,
    FollowUpTask,
    FollowUpTaskStatus,
    InboundMessage,
    Lead,
    LeadBucket,
    MailboxCursor,
)
from app.crm.service import LeadService
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

    def __init__(
        self,
        messages: dict[int, InboundEmailRecord] | None = None,
        uidvalidity_value: int | None = None,
    ) -> None:
        self.messages: dict[int, InboundEmailRecord] = dict(messages or {})
        self.uidvalidity_value = uidvalidity_value

    def list_since_uid(self, mailbox: str = "INBOX", since_uid: int = 0) -> list[InboundEmailRecord]:
        return [
            record for uid, record in sorted(self.messages.items()) if uid > since_uid
        ]

    def latest_uid(self, mailbox: str = "INBOX") -> int | None:
        return max(self.messages) if self.messages else None

    def uidvalidity(self, mailbox: str = "INBOX") -> int | None:
        return self.uidvalidity_value


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
    product_line = ProductLine(organization_id=organization.id, name=f"Product {domain}")
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
        def uidvalidity(self, mailbox: str = "INBOX") -> int | None:
            return None

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


def test_company_association_by_domain_fallback(session, organizations) -> None:
    organization = organizations["acme"]
    lead, _ = _make_lead(
        session, organization, domain="buyer.example", contact_email="anna@buyer.example"
    )
    imap = FakeImapConnector(
        {
            1: make_record(
                "msg-1", "Re: Offer", "We are interested.",
                sender_email="someone-else@buyer.example",
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


class FailingClassifierService(InboxService):
    def __init__(self, session, imap_connector, fail_on_call: int) -> None:
        super().__init__(session, imap_connector)
        self._calls = 0
        self._fail_on_call = fail_on_call

    def _classify(self, subject: str, body: str, product_line_name: str):
        self._calls += 1
        if self._calls == self._fail_on_call:
            raise RuntimeError("classify boom")
        return super()._classify(subject, body, product_line_name)


def test_mid_processing_failure_does_not_advance_cursor(session, organizations) -> None:
    organization = organizations["acme"]
    _make_lead(session, organization)
    imap = FakeImapConnector(
        {
            1: make_record("msg-1", "Re: 1", "We are interested."),
            2: make_record("msg-2", "Re: 2", "We are interested."),
        }
    )

    with pytest.raises(RuntimeError):
        FailingClassifierService(session, imap, fail_on_call=2).sync_organization_mailbox(
            organization.id
        )

    assert session.get(MailboxCursor, (organization.id, "INBOX")) is None
    assert session.scalar(select(func.count()).select_from(InboundMessage)) == 0


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Out of Office", "I am away from the office."),
        ("Re: hello", "We are not interested, please do not contact us."),
    ],
)
def test_terminal_intents_create_no_follow_up(session, organizations, subject, body) -> None:
    organization = organizations["acme"]
    _make_lead(session, organization)
    imap = FakeImapConnector({1: make_record("msg-1", subject, body)})

    InboxService(session, imap).sync_organization_mailbox(organization.id)

    message = session.scalar(select(InboundMessage))
    assert message is not None
    assert message.intent in {"out_of_office", "not_interested"}
    assert message.follow_up_task_id is None
    assert session.scalar(select(func.count()).select_from(FollowUpTask)) == 0


def test_uidvalidity_change_triggers_full_rescan(session, organizations) -> None:
    organization = organizations["acme"]
    _make_lead(session, organization)
    imap1 = FakeImapConnector(
        {10: make_record("msg-1", "Re: Offer", "We are interested.")}, uidvalidity_value=100
    )
    InboxService(session, imap1).sync_organization_mailbox(organization.id)

    cursor = session.get(MailboxCursor, (organization.id, "INBOX"))
    assert cursor is not None
    assert cursor.last_uid == 10
    assert cursor.uidvalidity == 100

    # Rebuilt mailbox: UIDs reassigned, a new message now sits below the old cursor.
    imap2 = FakeImapConnector(
        {
            1: make_record("msg-1", "Re: Offer", "We are interested."),
            2: make_record("msg-2", "Re: Offer", "We are interested."),
        },
        uidvalidity_value=200,
    )
    synced = InboxService(session, imap2).sync_organization_mailbox(organization.id)

    assert synced == 1
    cursor = session.get(MailboxCursor, (organization.id, "INBOX"))
    assert cursor is not None
    assert cursor.last_uid == 2
    assert cursor.uidvalidity == 200
    assert session.scalar(select(func.count()).select_from(InboundMessage)) == 2


def test_poll_organization_ids_includes_leads_and_cursors(session, organizations) -> None:
    acme = organizations["acme"]
    globex = organizations["globex"]
    _make_lead(session, acme)
    session.add(MailboxCursor(organization_id=acme.id, mailbox="INBOX", last_uid=0))
    session.add(MailboxCursor(organization_id=globex.id, mailbox="INBOX", last_uid=0))
    session.flush()

    ids = poll_organization_ids(session)

    assert set(ids) == {acme.id, globex.id}
    assert len(ids) == 2


def test_single_tenant_stores_unmatched_and_backfills_later(session, organizations) -> None:
    organization = organizations["acme"]
    # Acme is the sole tenant: it already has a lead for an unrelated domain.
    _make_lead(session, organization, domain="existing.example", contact_email="buyer@existing.example")
    imap = FakeImapConnector(
        {1: make_record("msg-1", "Re: Offer", "We are interested.", sender_email="new@newco.example")}
    )
    service = InboxService(session, imap)

    # The sender matches no lead yet, but single-tenant means the reply is stored unlinked.
    assert service.sync_organization_mailbox(organization.id) == 1
    message = session.scalar(
        select(InboundMessage).where(InboundMessage.provider_message_id == "msg-1")
    )
    assert message is not None
    assert message.lead_id is None
    assert message.follow_up_task_id is None

    lead, _ = _make_lead(
        session, organization, domain="newco.example", contact_email="new@newco.example"
    )
    cursor = session.get(MailboxCursor, (organization.id, "INBOX"))
    assert cursor is not None
    cursor.last_uid = 0
    session.commit()

    # Re-delivery backfills the association now that the lead exists.
    assert service.sync_organization_mailbox(organization.id) == 0
    session.refresh(message)
    assert message.lead_id == lead.id
    assert message.follow_up_task_id is not None
    timeline = session.scalars(
        select(FollowUpRecord).where(FollowUpRecord.lead_id == lead.id)
    ).all()
    assert any(record.activity_type == "reply_analyzed" for record in timeline)


def test_multi_org_skips_unmatched_reply(session, organizations) -> None:
    acme = organizations["acme"]
    globex = organizations["globex"]
    _make_lead(session, acme, domain="acme.example", contact_email="buyer@acme.example")
    _make_lead(session, globex, domain="globex.example", contact_email="buyer@globex.example")
    imap = FakeImapConnector(
        {
            1: make_record(
                "msg-1", "Re: Offer", "We are interested.", sender_email="stranger@other.example"
            )
        }
    )

    synced = InboxService(session, imap).sync_organization_mailbox(acme.id)

    assert synced == 0
    assert session.scalar(select(func.count()).select_from(InboundMessage)) == 0


def test_lead_creation_backfills_unlinked_reply(session, organizations) -> None:
    organization = organizations["acme"]
    # Acme is the sole tenant with an unrelated lead, so the reply is stored unlinked.
    _make_lead(
        session, organization, domain="existing.example", contact_email="buyer@existing.example"
    )
    imap = FakeImapConnector(
        {
            1: make_record(
                "msg-1", "Re: Offer", "We are interested.", sender_email="new@newco.example"
            )
        }
    )
    InboxService(session, imap).sync_organization_mailbox(organization.id)
    message = session.scalar(
        select(InboundMessage).where(InboundMessage.provider_message_id == "msg-1")
    )
    assert message is not None
    assert message.lead_id is None
    assert message.follow_up_task_id is None

    product_line = ProductLine(organization_id=organization.id, name="NewCo Line")
    session.add(product_line)
    session.flush()

    lead = LeadService(session).create_manual_lead(
        organization_id=organization.id,
        product_line_id=product_line.id,
        product_item_id=None,
        product_item_name="",
        company_name="NewCo",
        website="https://newco.example",
        target_market="US",
        buyer_profile=None,
        notes="",
        actor_user_id="actor",
    )
    session.commit()

    session.refresh(message)
    assert message.lead_id == lead.id
    assert message.follow_up_task_id is not None
    timeline = session.scalars(
        select(FollowUpRecord).where(FollowUpRecord.lead_id == lead.id)
    ).all()
    assert any(record.activity_type == "reply_analyzed" for record in timeline)


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


def test_router_filters_detail_and_follow_up_done() -> None:
    client, factory = configured_client()
    org_id = client.acme_id  # type: ignore[attr-defined]
    with factory.begin() as session:
        product_line = ProductLine(organization_id=org_id, name="Bearings")
        workflow_run = WorkflowRun(
            organization_id=org_id,
            agent_id="router-test",
            agent_version="1.0.0",
            input_json={},
            idempotency_key="router-test-1",
        )
        session.add_all([product_line, workflow_run])
        session.flush()
        lead = Lead(
            organization_id=org_id,
            workflow_run_id=workflow_run.id,
            product_line_id=product_line.id,
            company_name="Router Buyer",
            website="https://router.example",
            canonical_domain="router.example",
            target_market="US",
            score=70,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
        )
        session.add(lead)
        session.flush()
        task1 = FollowUpTask(
            organization_id=org_id,
            lead_id=lead.id,
            actor_user_id=None,
            title="t1",
            task_type="reply_follow_up",
            quote_status="",
            due_at=datetime(2026, 2, 1),
        )
        task2 = FollowUpTask(
            organization_id=org_id,
            lead_id=lead.id,
            actor_user_id=None,
            title="t2",
            task_type="reply_follow_up",
            quote_status="",
            due_at=datetime(2026, 3, 1),
        )
        session.add_all([task1, task2])
        session.flush()
        m1 = InboundMessage(
            organization_id=org_id,
            provider_message_id="m1",
            sender_email="a@router.example",
            subject="A",
            body_text="hello",
            received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            intent="interested",
            lead_id=lead.id,
            follow_up_task_id=task1.id,
        )
        m2 = InboundMessage(
            organization_id=org_id,
            provider_message_id="m2",
            sender_email="b@router.example",
            subject="B",
            body_text="hello",
            received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            intent="question",
            lead_id=lead.id,
            follow_up_task_id=task2.id,
            analysis_rationale="question rationale",
            suggested_reply="question reply",
        )
        m3 = InboundMessage(
            organization_id=org_id,
            provider_message_id="m3",
            sender_email="c@router.example",
            subject="C",
            body_text="hello",
            received_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            intent="other",
            lead_id=lead.id,
        )
        session.add_all([m1, m2, m3])
        session.flush()
        lead_id = lead.id
        m2_id = m2.id
        m3_id = m3.id
        task2_id = task2.id

    headers = bearer_headers(client.member_id)  # type: ignore[attr-defined]
    base = f"/organizations/{org_id}/inbox"

    with_task = client.get(f"{base}?has_follow_up=true", headers=headers).json()
    assert len(with_task) == 2

    without_task = client.get(f"{base}?has_follow_up=false", headers=headers).json()
    assert len(without_task) == 1
    assert without_task[0]["provider_message_id"] == "m3"

    after = client.get(f"{base}?due_from=2026-02-15T00:00:00", headers=headers).json()
    assert [item["provider_message_id"] for item in after] == ["m2"]

    before = client.get(f"{base}?due_before=2026-03-01T00:00:00", headers=headers).json()
    assert [item["provider_message_id"] for item in before] == ["m1"]

    detail = client.get(f"{base}/{m2_id}", headers=headers)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["analysis_rationale"] == "question rationale"
    assert detail_body["suggested_reply"] == "question reply"
    assert detail_body["linked_company_name"] == "Router Buyer"
    assert detail_body["due_at"] is not None

    done = client.post(f"{base}/{m2_id}/follow-up/done", headers=headers)
    assert done.status_code == 200
    assert done.json()["follow_up_status"] == "done"
    with factory.begin() as session:
        assert session.get(FollowUpTask, task2_id).status == FollowUpTaskStatus.DONE
        done_record = session.scalar(
            select(FollowUpRecord).where(
                FollowUpRecord.lead_id == lead_id,
                FollowUpRecord.activity_type == "task_done",
            )
        )
        assert done_record is not None
        assert done_record.actor_user_id == client.member_id  # type: ignore[attr-defined]

    conflict = client.post(f"{base}/{m3_id}/follow-up/done", headers=headers)
    assert conflict.status_code == 409
