import pytest

from app.crm.models import CRMContact, EmailDraft, EmailDraftStatus, Lead, LeadBucket
from app.crm.service import LeadService
from app.platform.models import ProductLine
from app.workflow.models import WorkflowRun


def _make_draft(session, organization, *, subject, body, evidence) -> EmailDraft:
    product_line = ProductLine(organization_id=organization.id, name="Lighting")
    workflow_run = WorkflowRun(
        organization_id=organization.id,
        agent_id="email",
        agent_version="1.0.0",
        input_json={},
        idempotency_key=f"email-quality-{body[:8]}",
    )
    session.add_all([product_line, workflow_run])
    session.flush()
    lead = Lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        company_name="Acme Buyer GmbH",
        website="https://acme-buyer.example",
        canonical_domain="acme-buyer.example",
        target_market="Germany",
        score=70,
        bucket=LeadBucket.NEEDS_ENRICHMENT,
    )
    session.add(lead)
    session.flush()
    contact = CRMContact(
        organization_id=organization.id,
        lead_id=lead.id,
        name="Anna Weber",
        email="anna@acme-buyer.example",
        is_primary=True,
    )
    session.add(contact)
    session.flush()
    draft = EmailDraft(
        organization_id=organization.id,
        lead_id=lead.id,
        contact_id=contact.id,
        product_line_id=product_line.id,
        status=EmailDraftStatus.PENDING_APPROVAL,
        subject=subject,
        body=body,
        recipient_email=contact.email,
        evidence_snapshot=evidence,
    )
    session.add(draft)
    session.flush()
    return draft


def test_review_approve_rejects_generic_draft(session, organizations) -> None:
    organization = organizations["acme"]
    draft = _make_draft(
        session,
        organization,
        subject="Hello",
        body="We offer good products. Please reply.",
        evidence=[],
    )

    with pytest.raises(ValueError) as caught:
        LeadService(session).review_email_draft(
            draft_id=draft.id,
            organization_id=organization.id,
            reviewer_user_id="reviewer",
            action="approve",
            rejection_reason="",
        )

    message = str(caught.value)
    assert "missing_product_evidence" in message
    assert "missing_personalization" in message


def test_review_approve_accepts_quality_draft(session, organizations) -> None:
    organization = organizations["acme"]
    draft = _make_draft(
        session,
        organization,
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. We can share tested "
            "specifications for your next range review. Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    reviewed = LeadService(session).review_email_draft(
        draft_id=draft.id,
        organization_id=organization.id,
        reviewer_user_id="reviewer",
        action="approve",
        rejection_reason="",
    )

    assert reviewed.status == EmailDraftStatus.READY_TO_SEND
