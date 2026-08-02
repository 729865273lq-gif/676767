from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.base.contracts import SearchResult
from app.crm.models import (
    CRMContact,
    EmailDraft,
    EmailDraftStatus,
    FollowUpRecord,
    Lead,
    LeadBucket,
    LeadEvidence,
    LeadStatus,
)
from app.crm.scoring import LeadQualification
from app.platform.models import ProductLine, utcnow
from app.workflow.models import WorkflowRun, WorkflowState


class LeadService:
    def __init__(self, session: Session):
        self.session = session

    def save_discovered_lead(
        self,
        *,
        organization_id: str,
        workflow_run_id: str,
        product_line_id: str,
        target_market: str,
        buyer_profile: str | None,
        result: SearchResult,
        qualification: LeadQualification,
    ) -> Lead:
        domain = canonical_domain(result.url)
        existing = self.session.scalar(
            select(Lead).where(
                Lead.organization_id == organization_id,
                Lead.canonical_domain == domain,
            )
        )
        if existing is None:
            lead = Lead(
                organization_id=organization_id,
                workflow_run_id=workflow_run_id,
                product_line_id=product_line_id,
                company_name=result.title,
                website=result.url,
                canonical_domain=domain,
                target_market=target_market,
                buyer_profile=buyer_profile,
                score=qualification.score,
                bucket=qualification.bucket,
                reasons=qualification.reasons,
                missing_signals=qualification.missing_signals,
            )
            self.session.add(lead)
            self.session.flush()
        else:
            lead = existing

        self.session.add(
            LeadEvidence(
                lead_id=lead.id,
                source_url=result.url,
                source_excerpt=result.snippet,
                signal_name="search_result",
            )
        )
        self.session.flush()
        return lead

    def create_manual_lead(
        self,
        *,
        organization_id: str,
        product_line_id: str,
        company_name: str,
        website: str,
        target_market: str,
        buyer_profile: str | None,
        notes: str,
        actor_user_id: str,
    ) -> Lead:
        normalized_website = normalize_website(website)
        domain = canonical_domain(normalized_website)
        existing = self.session.scalar(
            select(Lead).where(
                Lead.organization_id == organization_id,
                Lead.canonical_domain == domain,
            )
        )
        if existing is not None:
            raise ValueError("customer already exists")

        workflow_run = WorkflowRun(
            organization_id=organization_id,
            agent_id="manual_crm",
            agent_version="1.0.0",
            state=WorkflowState.COMPLETED,
            input_json={
                "company_name": company_name,
                "website": normalized_website,
                "target_market": target_market,
                "buyer_profile": buyer_profile,
                "actor_user_id": actor_user_id,
            },
            output_json={"source": "manual"},
            idempotency_key=f"manual-crm-{domain}",
        )
        self.session.add(workflow_run)
        self.session.flush()

        lead = Lead(
            organization_id=organization_id,
            workflow_run_id=workflow_run.id,
            product_line_id=product_line_id,
            company_name=company_name.strip(),
            website=normalized_website,
            canonical_domain=domain,
            target_market=target_market.strip(),
            buyer_profile=buyer_profile.strip() if buyer_profile else None,
            score=70,
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            status=LeadStatus.TO_CONTACT,
            reasons=["人工添加客户"],
            missing_signals=["公开证据待补充", "联系人待补充"],
        )
        self.session.add(lead)
        self.session.flush()
        self.session.add(
            LeadEvidence(
                lead_id=lead.id,
                source_url=normalized_website,
                source_excerpt=notes.strip() or "人工添加客户，待补充公开来源证据。",
                signal_name="manual_entry",
            )
        )
        self.session.flush()
        return lead

    def list_leads(
        self,
        *,
        organization_id: str,
        bucket: LeadBucket | None = None,
        workflow_run_id: str | None = None,
    ) -> list[Lead]:
        statement = select(Lead).where(Lead.organization_id == organization_id)
        if bucket is not None:
            statement = statement.where(Lead.bucket == bucket)
        if workflow_run_id is not None:
            statement = statement.where(Lead.workflow_run_id == workflow_run_id)
        return list(self.session.scalars(statement.order_by(Lead.score.desc(), Lead.company_name)))

    def get_lead(self, lead_id: str, organization_id: str) -> Lead:
        lead = self.session.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == organization_id)
        )
        if lead is None:
            raise LookupError("lead not found")
        return lead

    def delete_lead(self, lead_id: str, organization_id: str) -> None:
        lead = self.get_lead(lead_id, organization_id)
        self.session.execute(delete(EmailDraft).where(EmailDraft.lead_id == lead.id))
        self.session.execute(delete(CRMContact).where(CRMContact.lead_id == lead.id))
        self.session.execute(delete(FollowUpRecord).where(FollowUpRecord.lead_id == lead.id))
        self.session.execute(delete(LeadEvidence).where(LeadEvidence.lead_id == lead.id))
        self.session.delete(lead)
        self.session.flush()

    def update_lead_detail(
        self,
        *,
        lead_id: str,
        organization_id: str,
        status: LeadStatus,
        notes: str,
        owner_user_id: str | None,
    ) -> Lead:
        lead = self.get_lead(lead_id, organization_id)
        lead.status = status
        lead.notes = notes.strip()
        lead.owner_user_id = owner_user_id
        self.session.flush()
        return lead

    def evidence_for_lead(self, lead_id: str) -> list[LeadEvidence]:
        return list(
            self.session.scalars(
                select(LeadEvidence)
                .where(LeadEvidence.lead_id == lead_id)
                .order_by(LeadEvidence.captured_at)
            )
        )

    def add_follow_up(
        self,
        *,
        organization_id: str,
        lead_id: str,
        actor_user_id: str,
        activity_type: str,
        content: str,
        next_follow_up_at: datetime | None,
    ) -> FollowUpRecord:
        self.get_lead(lead_id, organization_id)
        record = FollowUpRecord(
            organization_id=organization_id,
            lead_id=lead_id,
            actor_user_id=actor_user_id,
            activity_type=activity_type.strip() or "note",
            content=content.strip(),
            next_follow_up_at=next_follow_up_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def follow_ups_for_lead(self, lead_id: str, organization_id: str) -> list[FollowUpRecord]:
        self.get_lead(lead_id, organization_id)
        return list(
            self.session.scalars(
                select(FollowUpRecord)
                .where(
                    FollowUpRecord.lead_id == lead_id,
                    FollowUpRecord.organization_id == organization_id,
                )
                .order_by(FollowUpRecord.created_at.desc())
            )
        )

    def add_contact(
        self,
        *,
        organization_id: str,
        lead_id: str,
        name: str,
        title: str,
        email: str,
        phone: str,
        linkedin_url: str,
        whatsapp: str,
        is_primary: bool,
    ) -> CRMContact:
        self.get_lead(lead_id, organization_id)
        has_existing_contact = (
            self.session.scalar(
                select(CRMContact.id)
                .where(CRMContact.lead_id == lead_id, CRMContact.organization_id == organization_id)
                .limit(1)
            )
            is not None
        )
        should_be_primary = is_primary or not has_existing_contact
        if should_be_primary:
            for contact in self.contacts_for_lead(lead_id, organization_id):
                contact.is_primary = False
        contact = CRMContact(
            organization_id=organization_id,
            lead_id=lead_id,
            name=name.strip(),
            title=title.strip(),
            email=email.strip(),
            phone=phone.strip(),
            linkedin_url=linkedin_url.strip(),
            whatsapp=whatsapp.strip(),
            is_primary=should_be_primary,
        )
        self.session.add(contact)
        self.session.flush()
        return contact

    def contacts_for_lead(self, lead_id: str, organization_id: str) -> list[CRMContact]:
        self.get_lead(lead_id, organization_id)
        return list(
            self.session.scalars(
                select(CRMContact)
                .where(
                    CRMContact.lead_id == lead_id,
                    CRMContact.organization_id == organization_id,
                )
                .order_by(CRMContact.is_primary.desc(), CRMContact.created_at.desc())
            )
        )

    def delete_contact(self, lead_id: str, contact_id: str, organization_id: str) -> None:
        self.get_lead(lead_id, organization_id)
        contact = self.session.scalar(
            select(CRMContact).where(
                CRMContact.id == contact_id,
                CRMContact.lead_id == lead_id,
                CRMContact.organization_id == organization_id,
            )
        )
        if contact is None:
            raise LookupError("contact not found")
        self.session.execute(delete(EmailDraft).where(EmailDraft.contact_id == contact.id))
        self.session.delete(contact)
        self.session.flush()

    def create_email_draft(
        self,
        *,
        organization_id: str,
        lead_id: str,
        contact_id: str,
        actor_user_id: str,
    ) -> EmailDraft:
        lead = self.get_lead(lead_id, organization_id)
        contact = self._get_contact(contact_id, lead_id, organization_id)
        if not contact.email.strip():
            raise ValueError("contact email is required")
        product_line = self.session.scalar(
            select(ProductLine).where(
                ProductLine.id == lead.product_line_id,
                ProductLine.organization_id == organization_id,
            )
        )
        if product_line is None:
            raise LookupError("product line not found")
        evidence = self.evidence_for_lead(lead.id)[:3]
        evidence_snapshot = [
            {
                "signal_name": item.signal_name,
                "source_excerpt": item.source_excerpt,
                "source_url": item.source_url,
            }
            for item in evidence
        ]
        subject = f"{product_line.name} supply discussion for {lead.company_name}"
        body = build_email_body(lead=lead, contact=contact, product_line=product_line, evidence=evidence)
        draft = EmailDraft(
            organization_id=organization_id,
            lead_id=lead.id,
            contact_id=contact.id,
            product_line_id=product_line.id,
            created_by_user_id=actor_user_id,
            status=EmailDraftStatus.PENDING_APPROVAL,
            subject=subject,
            body=body,
            evidence_snapshot=evidence_snapshot,
        )
        self.session.add(draft)
        self.session.flush()
        return draft

    def list_email_drafts(
        self,
        *,
        organization_id: str,
        status_filter: EmailDraftStatus | None = None,
    ) -> list[EmailDraft]:
        statement = select(EmailDraft).where(EmailDraft.organization_id == organization_id)
        if status_filter is not None:
            statement = statement.where(EmailDraft.status == status_filter)
        return list(
            self.session.scalars(
                statement.order_by(EmailDraft.status, EmailDraft.created_at.desc())
            )
        )

    def get_email_draft(self, draft_id: str, organization_id: str) -> EmailDraft:
        draft = self.session.scalar(
            select(EmailDraft).where(
                EmailDraft.id == draft_id,
                EmailDraft.organization_id == organization_id,
            )
        )
        if draft is None:
            raise LookupError("email draft not found")
        return draft

    def update_email_draft(
        self,
        *,
        draft_id: str,
        organization_id: str,
        subject: str,
        body: str,
    ) -> EmailDraft:
        draft = self.get_email_draft(draft_id, organization_id)
        if draft.status != EmailDraftStatus.PENDING_APPROVAL:
            raise ValueError("only pending drafts can be edited")
        draft.subject = subject.strip()
        draft.body = body.strip()
        self.session.flush()
        return draft

    def review_email_draft(
        self,
        *,
        draft_id: str,
        organization_id: str,
        reviewer_user_id: str,
        action: str,
        rejection_reason: str,
    ) -> EmailDraft:
        draft = self.get_email_draft(draft_id, organization_id)
        if draft.status != EmailDraftStatus.PENDING_APPROVAL:
            raise ValueError("only pending drafts can be reviewed")
        if action == "approve":
            draft.status = EmailDraftStatus.READY_TO_SEND
            draft.rejection_reason = ""
        elif action == "reject":
            draft.status = EmailDraftStatus.REJECTED
            draft.rejection_reason = rejection_reason.strip()
        else:
            raise ValueError("review action must be approve or reject")
        draft.reviewed_by_user_id = reviewer_user_id
        draft.reviewed_at = utcnow()
        self.session.flush()
        return draft

    def _get_contact(self, contact_id: str, lead_id: str, organization_id: str) -> CRMContact:
        contact = self.session.scalar(
            select(CRMContact).where(
                CRMContact.id == contact_id,
                CRMContact.lead_id == lead_id,
                CRMContact.organization_id == organization_id,
            )
        )
        if contact is None:
            raise LookupError("contact not found")
        return contact


def canonical_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        raise ValueError("search result must contain an absolute website URL")
    return domain


def normalize_website(website: str) -> str:
    value = website.strip()
    if not value:
        raise ValueError("website is required")
    if "://" not in value:
        value = f"https://{value}"
    canonical_domain(value)
    return value


def build_email_body(
    *,
    lead: Lead,
    contact: CRMContact,
    product_line: ProductLine,
    evidence: list[LeadEvidence],
) -> str:
    evidence_lines = [
        f"- {item.source_excerpt} ({item.source_url})"
        for item in evidence
        if item.source_excerpt.strip()
    ]
    evidence_text = "\n".join(evidence_lines) if evidence_lines else "- We reviewed your public website information."
    notes = f"\n\nInternal context for reviewer: {lead.notes}" if lead.notes else ""
    title = f", {contact.title}" if contact.title else ""
    return (
        f"Dear {contact.name}{title},\n\n"
        f"I am reaching out from our export team regarding {product_line.name}. "
        f"We noticed that {lead.company_name} appears relevant to {lead.target_market}"
        f"{f' and the {lead.buyer_profile} segment' if lead.buyer_profile else ''}.\n\n"
        f"Public evidence used for this draft:\n{evidence_text}\n\n"
        "If you are currently evaluating suppliers or product options in this area, "
        "I would be glad to share a concise catalog and discuss whether our solution is a fit.\n\n"
        "Would it be reasonable to send you more details or schedule a brief introduction?\n\n"
        "Best regards,\n"
        "Trade Axis Sales Team"
        f"{notes}"
    )
