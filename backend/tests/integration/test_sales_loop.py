from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.connectors.email.imap import InboundEmailRecord
from app.crm.inbox import InboxService, ReplyIntent
from app.crm.models import CRMContact, FollowUpRecord, InboundMessage, Lead, LeadBucket
from app.platform.models import ProductLine
from app.workflow.models import WorkflowRun


class FakeImapConnector:
    connector_id = "fake-imap"
    version = "v1"

    def __init__(self, messages: dict[int, InboundEmailRecord]) -> None:
        self.messages = messages

    def list_since_uid(self, mailbox: str = "INBOX", since_uid: int = 0) -> list[InboundEmailRecord]:
        return [record for uid, record in sorted(self.messages.items()) if uid > since_uid]

    def latest_uid(self, mailbox: str = "INBOX") -> int | None:
        return max(self.messages) if self.messages else None


def test_reply_sync_creates_analysis_follow_up_and_timeline(session, organizations) -> None:
    """Full sales loop: an outbound contact replies and the reply is analyzed end-to-end."""
    organization = organizations["acme"]
    product_line = ProductLine(organization_id=organization.id, name="Industrial Bearings")
    workflow_run = WorkflowRun(
        organization_id=organization.id,
        agent_id="customer",
        agent_version="1.0.0",
        input_json={},
        idempotency_key="sales-loop",
    )
    session.add_all([product_line, workflow_run])
    session.flush()
    lead = Lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        company_name="Northwind Trading",
        website="https://northwind.example",
        canonical_domain="northwind.example",
        target_market="Netherlands",
        score=80,
        bucket=LeadBucket.PRIORITY_RECOMMENDATION,
    )
    session.add(lead)
    session.flush()
    contact = CRMContact(
        organization_id=organization.id,
        lead_id=lead.id,
        name="Jan de Vries",
        email="jan@northwind.example",
        is_primary=True,
    )
    session.add(contact)
    session.flush()

    reply = InboundEmailRecord(
        provider_message_id="<reply-001@northwind.example>",
        thread_id="<reply-001@northwind.example>",
        sender_email="jan@northwind.example",
        sender_name="Jan de Vries",
        subject="Re: Your bearing offer",
        body_text="We are interested in your industrial bearings. Please send a catalog.",
        received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        attachments_count=0,
    )
    imap = FakeImapConnector({10: reply})

    synced = InboxService(session, imap).sync_organization_mailbox(organization.id)

    assert synced == 1
    message = session.scalar(
        select(InboundMessage).where(InboundMessage.organization_id == organization.id)
    )
    assert message is not None
    assert message.intent in {intent.value for intent in ReplyIntent}
    assert message.follow_up_task_id is not None
    timeline = session.scalars(
        select(FollowUpRecord).where(FollowUpRecord.lead_id == lead.id)
    ).all()
    assert any(record.activity_type == "reply_analyzed" for record in timeline)
