from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.base.contracts import OutboundMessage, SearchResult
from app.connectors.contact_discovery import DiscoveredContact
from app.connectors.email_verification import EmailVerificationResult
from app.crm.email_quality import QualityReport, evaluate_draft, quality_gate_error
from app.crm.models import (
    CRMContact,
    EmailDraft,
    EmailDraftStatus,
    FollowUpRecord,
    FollowUpTask,
    FollowUpTaskStatus,
    Lead,
    LeadBucket,
    LeadEvidence,
    LeadStatus,
    QuoteDraft,
    QuoteDraftStatus,
    WebsiteInquiry,
    WebsiteInquiryStatus,
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
        domain = result.canonical_key.strip() or canonical_domain(result.url)
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
            lead.last_discovered_at = utcnow()

        if any([result.email, result.phone, result.whatsapp, result.social_profiles]):
            self._upsert_public_contact_from_search(
                lead=lead,
                result=result,
            )

        self.session.add(
            LeadEvidence(
                lead_id=lead.id,
                source_url=result.source_url or result.url,
                source_excerpt=result.snippet,
                signal_name="search_result",
            )
        )
        self.session.flush()
        return lead

    def _upsert_public_contact_from_search(
        self,
        *,
        lead: Lead,
        result: SearchResult,
    ) -> None:
        discovered = DiscoveredContact(
            name=lead.company_name,
            title="公开企业联系方式",
            email=result.email,
            phone=result.phone,
            whatsapp=result.whatsapp,
            social_profiles=result.social_profiles,
            source_url=result.source_url or result.url,
            source="Search result",
        )
        contacts = self._contacts_without_lead_check(lead.id, lead.organization_id)
        contact = find_matching_contact(contacts, discovered)
        if contact is not None:
            merge_discovered_contact(contact, discovered)
            return
        self.session.add(
            CRMContact(
                organization_id=lead.organization_id,
                lead_id=lead.id,
                name=lead.company_name,
                title="公开企业联系方式",
                email=result.email.strip(),
                phone=result.phone.strip(),
                whatsapp=result.whatsapp.strip(),
                social_profiles=normalize_social_profiles(result.social_profiles),
                source_url=(result.source_url or result.url).strip(),
                is_primary=not contacts,
            )
        )

    def _contacts_without_lead_check(self, lead_id: str, organization_id: str) -> list[CRMContact]:
        return list(
            self.session.scalars(
                select(CRMContact).where(
                    CRMContact.lead_id == lead_id,
                    CRMContact.organization_id == organization_id,
                )
            )
        )

    def create_manual_lead(
        self,
        *,
        organization_id: str,
        product_line_id: str,
        product_item_id: str | None,
        product_item_name: str,
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
                "product_item_id": product_item_id,
                "product_item_name": product_item_name.strip(),
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
        return list(
            self.session.scalars(
                statement.order_by(
                    Lead.last_discovered_at.desc(),
                    Lead.created_at.desc(),
                    Lead.company_name,
                )
            )
        )

    def list_leads_discovered_between(
        self,
        *,
        organization_id: str,
        discovered_from: datetime,
        discovered_before: datetime,
        limit: int = 50,
    ) -> list[Lead]:
        statement = (
            select(Lead)
            .where(
                Lead.organization_id == organization_id,
                Lead.last_discovered_at >= discovered_from,
                Lead.last_discovered_at < discovered_before,
            )
            .order_by(Lead.last_discovered_at.desc(), Lead.company_name)
            .limit(min(max(limit, 1), 50))
        )
        return list(self.session.scalars(statement))

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
        self.session.execute(delete(QuoteDraft).where(QuoteDraft.lead_id == lead.id))
        self.session.execute(delete(CRMContact).where(CRMContact.lead_id == lead.id))
        self.session.execute(delete(FollowUpRecord).where(FollowUpRecord.lead_id == lead.id))
        self.session.execute(delete(FollowUpTask).where(FollowUpTask.lead_id == lead.id))
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
        lead = self.get_lead(lead_id, organization_id)
        normalized_activity_type = activity_type.strip() or "note"
        if normalized_activity_type == "reply":
            lead.status = LeadStatus.INTERESTED
        record = FollowUpRecord(
            organization_id=organization_id,
            lead_id=lead_id,
            actor_user_id=actor_user_id,
            activity_type=normalized_activity_type,
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

    def list_follow_ups(
        self,
        *,
        organization_id: str,
        limit: int = 20,
    ) -> list[tuple[FollowUpRecord, Lead]]:
        statement = (
            select(FollowUpRecord, Lead)
            .join(Lead, Lead.id == FollowUpRecord.lead_id)
            .where(FollowUpRecord.organization_id == organization_id, Lead.organization_id == organization_id)
            .order_by(
                FollowUpRecord.next_follow_up_at.is_(None),
                FollowUpRecord.next_follow_up_at,
                FollowUpRecord.created_at.desc(),
            )
            .limit(limit)
        )
        return list(self.session.execute(statement).all())

    def create_follow_up_task(
        self,
        *,
        organization_id: str,
        lead_id: str,
        actor_user_id: str,
        title: str,
        task_type: str,
        quote_status: str,
        due_at: datetime | None,
    ) -> FollowUpTask:
        lead = self.get_lead(lead_id, organization_id)
        normalized_task_type = task_type.strip() or "follow_up"
        normalized_quote_status = quote_status.strip()
        if normalized_task_type == "quote" or normalized_quote_status:
            lead.status = LeadStatus.QUOTING
        task = FollowUpTask(
            organization_id=organization_id,
            lead_id=lead.id,
            actor_user_id=actor_user_id,
            title=title.strip(),
            task_type=normalized_task_type,
            quote_status=normalized_quote_status,
            due_at=due_at,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def follow_up_tasks_for_lead(self, lead_id: str, organization_id: str) -> list[FollowUpTask]:
        self.get_lead(lead_id, organization_id)
        return list(
            self.session.scalars(
                select(FollowUpTask)
                .where(
                    FollowUpTask.lead_id == lead_id,
                    FollowUpTask.organization_id == organization_id,
                )
                .order_by(
                    FollowUpTask.status,
                    FollowUpTask.due_at.is_(None),
                    FollowUpTask.due_at,
                    FollowUpTask.created_at.desc(),
                )
            )
        )

    def list_follow_up_tasks(
        self,
        *,
        organization_id: str,
        status_filter: FollowUpTaskStatus | None = FollowUpTaskStatus.OPEN,
        limit: int = 20,
    ) -> list[tuple[FollowUpTask, Lead]]:
        statement = (
            select(FollowUpTask, Lead)
            .join(Lead, Lead.id == FollowUpTask.lead_id)
            .where(FollowUpTask.organization_id == organization_id, Lead.organization_id == organization_id)
        )
        if status_filter is not None:
            statement = statement.where(FollowUpTask.status == status_filter)
        statement = statement.order_by(
            FollowUpTask.status,
            FollowUpTask.due_at.is_(None),
            FollowUpTask.due_at,
            FollowUpTask.created_at.desc(),
        ).limit(limit)
        return list(self.session.execute(statement).all())

    def complete_follow_up_task(
        self,
        *,
        organization_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> FollowUpTask:
        task = self.session.scalar(
            select(FollowUpTask).where(
                FollowUpTask.id == task_id,
                FollowUpTask.organization_id == organization_id,
            )
        )
        if task is None:
            raise LookupError("follow-up task not found")
        self.get_lead(task.lead_id, organization_id)
        task.status = FollowUpTaskStatus.DONE
        task.completed_at = utcnow()
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=task.lead_id,
                actor_user_id=actor_user_id,
                activity_type="task_done",
                content=f"Completed task: {task.title}",
                next_follow_up_at=None,
            )
        )
        self.session.flush()
        return task

    def create_website_inquiry(
        self,
        *,
        organization_id: str,
        product_line_id: str,
        product_item_id: str | None,
        product_item_name: str,
        company_name: str,
        contact_name: str,
        email: str,
        phone: str,
        website: str,
        target_market: str,
        message: str,
        source_url: str,
    ) -> WebsiteInquiry:
        inquiry = WebsiteInquiry(
            organization_id=organization_id,
            product_line_id=product_line_id,
            product_item_id=product_item_id,
            product_item_name=product_item_name.strip(),
            company_name=company_name.strip(),
            contact_name=contact_name.strip(),
            email=email.strip(),
            phone=phone.strip(),
            website=website.strip(),
            target_market=target_market.strip(),
            message=message.strip(),
            source_url=source_url.strip(),
        )
        self.session.add(inquiry)
        self.session.flush()
        return inquiry

    def list_website_inquiries(
        self,
        *,
        organization_id: str,
        status_filter: WebsiteInquiryStatus | None = None,
    ) -> list[WebsiteInquiry]:
        statement = select(WebsiteInquiry).where(WebsiteInquiry.organization_id == organization_id)
        if status_filter is not None:
            statement = statement.where(WebsiteInquiry.status == status_filter)
        return list(
            self.session.scalars(
                statement.order_by(WebsiteInquiry.status, WebsiteInquiry.created_at.desc())
            )
        )

    def get_website_inquiry(self, inquiry_id: str, organization_id: str) -> WebsiteInquiry:
        inquiry = self.session.scalar(
            select(WebsiteInquiry).where(
                WebsiteInquiry.id == inquiry_id,
                WebsiteInquiry.organization_id == organization_id,
            )
        )
        if inquiry is None:
            raise LookupError("website inquiry not found")
        return inquiry

    def convert_website_inquiry(
        self,
        *,
        inquiry_id: str,
        organization_id: str,
        actor_user_id: str,
    ) -> tuple[WebsiteInquiry, Lead]:
        inquiry = self.get_website_inquiry(inquiry_id, organization_id)
        if inquiry.status != WebsiteInquiryStatus.NEW:
            raise ValueError("only new website inquiries can be converted")
        if inquiry.product_line_id is None:
            raise ValueError("product line is required to convert inquiry")

        website = inquiry.website.strip() or website_from_email(inquiry.email)
        product_context = f"Product inquiry: {inquiry.product_item_name}\n\n" if inquiry.product_item_name else ""
        lead = self.create_manual_lead(
            organization_id=organization_id,
            product_line_id=inquiry.product_line_id,
            product_item_id=inquiry.product_item_id,
            product_item_name=inquiry.product_item_name,
            company_name=inquiry.company_name,
            website=website,
            target_market=inquiry.target_market or "Unspecified",
            buyer_profile="Website inquiry",
            notes=f"{product_context}{inquiry.message}",
            actor_user_id=actor_user_id,
        )
        lead.status = LeadStatus.INTERESTED
        self.add_contact(
            organization_id=organization_id,
            lead_id=lead.id,
            name=inquiry.contact_name,
            title="",
            email=inquiry.email,
            phone=inquiry.phone,
            linkedin_url="",
            whatsapp="",
            is_primary=True,
        )
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_user_id=actor_user_id,
                activity_type="inquiry",
                content=(
                    f"Website inquiry for {inquiry.product_item_name}: {inquiry.message}"
                    if inquiry.product_item_name
                    else f"Website inquiry: {inquiry.message}"
                ),
                next_follow_up_at=None,
            )
        )
        inquiry.status = WebsiteInquiryStatus.CONVERTED
        inquiry.lead_id = lead.id
        inquiry.converted_at = utcnow()
        self.session.flush()
        return inquiry, lead

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
        social_profiles: list[dict[str, str]] | None = None,
        source_url: str = "",
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
            social_profiles=normalize_social_profiles(social_profiles or []),
            source_url=source_url.strip(),
            is_primary=should_be_primary,
        )
        self.session.add(contact)
        self.session.flush()
        self.refresh_lead_contact_summary(lead_id, organization_id)
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
        self.refresh_lead_contact_summary(lead_id, organization_id)

    def refresh_lead_contact_summary(
        self,
        lead_id: str,
        organization_id: str,
        *,
        scan_status: str | None = None,
        message: str = "",
        scanned: bool = False,
    ) -> Lead:
        lead = self.get_lead(lead_id, organization_id)
        contacts = self._contacts_without_lead_check(lead_id, organization_id)
        emails = {contact.email.strip().casefold() for contact in contacts if contact.email.strip()}
        phones = {normalize_phone_key(contact.phone) for contact in contacts if contact.phone.strip()}
        social_urls: set[str] = set()
        for contact in contacts:
            if contact.linkedin_url.strip():
                social_urls.add(normalize_url_key(contact.linkedin_url))
            if contact.whatsapp.strip():
                social_urls.add(normalize_url_key(contact.whatsapp))
            social_urls.update(
                normalize_url_key(profile["url"])
                for profile in normalize_social_profiles(contact.social_profiles or [])
            )
        lead.contact_email_count = len(emails)
        lead.contact_phone_count = len({phone for phone in phones if phone})
        lead.contact_social_count = len({url for url in social_urls if url})
        if emails:
            lead.contact_discovery_status = "has_email"
        elif phones or social_urls:
            lead.contact_discovery_status = "has_contact"
        elif scan_status == "needs_review":
            lead.contact_discovery_status = "needs_review"
        elif scan_status:
            lead.contact_discovery_status = scan_status
        else:
            lead.contact_discovery_status = "not_scanned"
        lead.contact_discovery_message = message.strip()[:500]
        if scanned:
            lead.contact_discovered_at = utcnow()
        self.session.flush()
        return lead

    def verify_contact_email(
        self,
        *,
        organization_id: str,
        lead_id: str,
        contact_id: str,
        actor_user_id: str,
        result: EmailVerificationResult,
    ) -> CRMContact:
        contact = self._get_contact(contact_id, lead_id, organization_id)
        if not contact.email:
            raise ValueError("contact email is required")
        contact.email_verification_provider = result.provider
        contact.email_verification_status = result.status
        contact.email_verification_sub_status = result.sub_status
        contact.email_verified_at = utcnow()
        status_text = result.status
        if result.sub_status:
            status_text = f"{status_text}/{result.sub_status}"
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=lead_id,
                actor_user_id=actor_user_id,
                activity_type="email_verified",
                content=f"Email verification for {contact.name} <{contact.email}>: {status_text} via {result.provider}.",
                next_follow_up_at=None,
            )
        )
        self.session.flush()
        return contact

    def add_discovered_contacts(
        self,
        *,
        organization_id: str,
        lead_id: str,
        actor_user_id: str,
        discovered_contacts: list[DiscoveredContact],
    ) -> list[CRMContact]:
        lead = self.get_lead(lead_id, organization_id)
        existing_contacts = self._contacts_without_lead_check(lead_id, organization_id)
        changed_contacts: list[CRMContact] = []
        sources: set[str] = set()
        for discovered in discovered_contacts:
            email = discovered.email.strip()
            if not discovered_channel_keys(discovered):
                continue
            sources.add(discovered.source or "public source")
            title = discovered.title.strip()
            if discovered.confidence is not None or discovered.verification_status:
                details = []
                if discovered.confidence is not None:
                    details.append(f"Hunter confidence {discovered.confidence}")
                if discovered.verification_status:
                    details.append(f"verification {discovered.verification_status}")
                title = f"{title} ({', '.join(details)})".strip() if title else ", ".join(details)
            normalized_discovered = DiscoveredContact(
                name=discovered.name.strip(),
                title=title,
                email=email,
                phone=discovered.phone.strip(),
                linkedin_url=discovered.linkedin_url.strip(),
                whatsapp=discovered.whatsapp.strip(),
                social_profiles=normalize_social_profiles(discovered.social_profiles),
                source_url=discovered.source_url.strip(),
                confidence=discovered.confidence,
                verification_status=discovered.verification_status,
                source=discovered.source,
            )
            existing = find_matching_contact(existing_contacts, normalized_discovered)
            if existing is not None:
                if (
                    merge_discovered_contact(existing, normalized_discovered)
                    and existing not in changed_contacts
                ):
                    changed_contacts.append(existing)
                continue
            contact = self.add_contact(
                organization_id=organization_id,
                lead_id=lead_id,
                name=normalized_discovered.name or (email.split("@")[0] if email else lead.company_name),
                title=title,
                email=email,
                phone=normalized_discovered.phone,
                linkedin_url=normalized_discovered.linkedin_url,
                whatsapp=normalized_discovered.whatsapp,
                is_primary=False,
                social_profiles=normalized_discovered.social_profiles,
                source_url=normalized_discovered.source_url,
            )
            existing_contacts.append(contact)
            changed_contacts.append(contact)

        if changed_contacts:
            if lead.status == LeadStatus.NEW:
                lead.status = LeadStatus.TO_CONTACT
            source_text = ", ".join(sorted(sources)) or "public sources"
            self.session.add(
                FollowUpRecord(
                    organization_id=organization_id,
                    lead_id=lead.id,
                    actor_user_id=actor_user_id,
                    activity_type="contact_discovery",
                    content=(
                        f"Found or updated {len(changed_contacts)} public contact record(s) "
                        f"for {lead.company_name} via {source_text}."
                    ),
                    next_follow_up_at=None,
                )
            )
        self.refresh_lead_contact_summary(lead_id, organization_id)
        self.session.flush()
        return changed_contacts

    def create_quote_draft(
        self,
        *,
        organization_id: str,
        lead_id: str,
        actor_user_id: str,
        title: str,
        currency: str,
        incoterm: str,
        valid_until: datetime | None,
        line_items: list[dict[str, str | float | int]],
        notes: str,
    ) -> QuoteDraft:
        lead = self.get_lead(lead_id, organization_id)
        product_line_exists = self.session.scalar(
            select(ProductLine.id).where(
                ProductLine.id == lead.product_line_id,
                ProductLine.organization_id == organization_id,
            )
        )
        if product_line_exists is None:
            raise LookupError("product line not found")
        draft = QuoteDraft(
            organization_id=organization_id,
            lead_id=lead.id,
            product_line_id=lead.product_line_id,
            created_by_user_id=actor_user_id,
            status=QuoteDraftStatus.DRAFT,
            title=title.strip(),
            currency=currency.strip().upper() or "USD",
            incoterm=incoterm.strip().upper() or "FOB",
            valid_until=valid_until,
            line_items=normalize_quote_line_items(line_items),
            notes=notes.strip(),
        )
        lead.status = LeadStatus.QUOTING
        self.session.add(draft)
        self.session.flush()
        return draft

    def quote_drafts_for_lead(self, lead_id: str, organization_id: str) -> list[QuoteDraft]:
        self.get_lead(lead_id, organization_id)
        return list(
            self.session.scalars(
                select(QuoteDraft)
                .where(
                    QuoteDraft.lead_id == lead_id,
                    QuoteDraft.organization_id == organization_id,
                )
                .order_by(QuoteDraft.status, QuoteDraft.created_at.desc())
            )
        )

    def list_quote_drafts(
        self,
        *,
        organization_id: str,
        status_filter: QuoteDraftStatus | None = QuoteDraftStatus.DRAFT,
        limit: int = 20,
    ) -> list[tuple[QuoteDraft, Lead]]:
        statement = (
            select(QuoteDraft, Lead)
            .join(Lead, Lead.id == QuoteDraft.lead_id)
            .where(QuoteDraft.organization_id == organization_id, Lead.organization_id == organization_id)
        )
        if status_filter is not None:
            statement = statement.where(QuoteDraft.status == status_filter)
        statement = statement.order_by(QuoteDraft.status, QuoteDraft.created_at.desc()).limit(limit)
        return list(self.session.execute(statement).all())

    def get_quote_draft(self, draft_id: str, organization_id: str) -> QuoteDraft:
        draft = self.session.scalar(
            select(QuoteDraft).where(
                QuoteDraft.id == draft_id,
                QuoteDraft.organization_id == organization_id,
            )
        )
        if draft is None:
            raise LookupError("quote draft not found")
        return draft

    def update_quote_draft(
        self,
        *,
        draft_id: str,
        organization_id: str,
        title: str,
        currency: str,
        incoterm: str,
        valid_until: datetime | None,
        line_items: list[dict[str, str | float | int]],
        notes: str,
    ) -> QuoteDraft:
        draft = self.get_quote_draft(draft_id, organization_id)
        if draft.status != QuoteDraftStatus.DRAFT:
            raise ValueError("only draft quotations can be edited")
        draft.title = title.strip()
        draft.currency = currency.strip().upper() or "USD"
        draft.incoterm = incoterm.strip().upper() or "FOB"
        draft.valid_until = valid_until
        draft.line_items = normalize_quote_line_items(line_items)
        draft.notes = notes.strip()
        self.session.flush()
        return draft

    def mark_quote_draft_sent(
        self,
        *,
        draft_id: str,
        organization_id: str,
        actor_user_id: str,
    ) -> QuoteDraft:
        draft = self.get_quote_draft(draft_id, organization_id)
        if draft.status != QuoteDraftStatus.DRAFT:
            raise ValueError("only draft quotations can be marked sent")
        lead = self.get_lead(draft.lead_id, organization_id)
        sent_at = utcnow()
        draft.status = QuoteDraftStatus.SENT
        draft.sent_by_user_id = actor_user_id
        draft.sent_at = sent_at
        lead.status = LeadStatus.QUOTING
        total = quote_total(draft.line_items)
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_user_id=actor_user_id,
                activity_type="quote_sent",
                content=f"已人工发送报价给 {lead.company_name}：{draft.title}，金额 {draft.currency} {total:.2f}",
                next_follow_up_at=sent_at + timedelta(days=3),
                created_at=sent_at,
            )
        )
        self.session.flush()
        return draft

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
        subject = build_email_subject(lead=lead, product_line=product_line)
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
            recipient_email=contact.email.strip().lower(),
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

    def get_email_draft_for_update(self, draft_id: str, organization_id: str) -> EmailDraft:
        draft = self.session.scalar(
            select(EmailDraft)
            .where(
                EmailDraft.id == draft_id,
                EmailDraft.organization_id == organization_id,
            )
            .with_for_update()
        )
        if draft is None:
            raise LookupError("email draft not found")
        return draft

    def evaluate_email_draft_quality(self, draft: EmailDraft) -> QualityReport:
        product_line = self.session.scalar(
            select(ProductLine).where(ProductLine.id == draft.product_line_id)
        )
        lead = self.session.scalar(select(Lead).where(Lead.id == draft.lead_id))
        contact = self.session.scalar(select(CRMContact).where(CRMContact.id == draft.contact_id))
        return evaluate_draft(
            subject=draft.subject,
            body=draft.body,
            evidence=draft.evidence_snapshot,
            # No model carries a per-organization outreach language yet; default to
            # English here. When a language setting lands (e.g. organization.outreach_language),
            # resolve it and pass it as requested_language.
            requested_language="en",
            product_context=email_product_context(product_line),
            contact_context=email_contact_context(lead, contact),
        )

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

    def update_draft_contact_email(
        self,
        *,
        draft_id: str,
        organization_id: str,
        actor_user_id: str,
        email: str,
    ) -> EmailDraft:
        draft = self.get_email_draft(draft_id, organization_id)
        if draft.status == EmailDraftStatus.READY_TO_SEND:
            raise ValueError("return the draft to review before changing the contact email")
        contact = self._get_contact(draft.contact_id, draft.lead_id, organization_id)
        normalized_email = email.strip().lower()
        if not OUTREACH_EMAIL_PATTERN.fullmatch(normalized_email):
            raise ValueError("a valid contact email is required")
        if contact.email.lower() == normalized_email:
            return draft
        previous_email = contact.email
        contact.email = normalized_email
        contact.email_verification_provider = ""
        contact.email_verification_status = ""
        contact.email_verification_sub_status = ""
        contact.email_verified_at = None
        if draft.status == EmailDraftStatus.PENDING_APPROVAL:
            draft.recipient_email = normalized_email
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=draft.lead_id,
                actor_user_id=actor_user_id,
                activity_type="contact_email_updated",
                content=(
                    f"Contact email updated from {previous_email or '(empty)'} to "
                    f"{normalized_email} during draft review. Verification was reset."
                ),
                next_follow_up_at=None,
            )
        )
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
            report = self.evaluate_email_draft_quality(draft)
            if not report.passed:
                raise quality_gate_error(report)
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

    def mark_email_draft_sent(
        self,
        *,
        draft_id: str,
        organization_id: str,
        actor_user_id: str,
        provider_message_id: str = "",
    ) -> EmailDraft:
        draft = self.get_email_draft(draft_id, organization_id)
        if draft.status != EmailDraftStatus.READY_TO_SEND:
            raise ValueError("only ready-to-send drafts can be marked sent")
        lead = self.get_lead(draft.lead_id, organization_id)
        contact = self._get_contact(draft.contact_id, draft.lead_id, organization_id)
        sent_at = utcnow()
        draft.status = EmailDraftStatus.SENT
        draft.sent_by_user_id = actor_user_id
        draft.sent_at = sent_at
        draft.provider_message_id = provider_message_id
        lead.status = LeadStatus.CONTACTED
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_user_id=actor_user_id,
                activity_type="email_sent",
                content=f"已人工发送开发信给 {contact.name} <{contact.email}>：{draft.subject}",
                next_follow_up_at=sent_at + timedelta(days=3),
                created_at=sent_at,
            )
        )
        self.session.flush()
        return draft

    def email_draft_outbound_message(
        self,
        *,
        draft_id: str,
        organization_id: str,
    ) -> tuple[EmailDraft, OutboundMessage]:
        draft = self.get_email_draft(draft_id, organization_id)
        if draft.status != EmailDraftStatus.READY_TO_SEND:
            raise ValueError("only ready-to-send drafts can be sent")
        contact = self._get_contact(draft.contact_id, draft.lead_id, organization_id)
        if not contact.email.strip():
            raise ValueError("contact email is required")
        assert_contact_email_can_send(contact)
        return draft, OutboundMessage(
            recipients=[draft.recipient_email.strip() or contact.email.strip()],
            subject=draft.subject.strip(),
            body=draft.body.strip(),
        )

    def get_contact(self, contact_id: str, lead_id: str, organization_id: str) -> CRMContact:
        return self._get_contact(contact_id, lead_id, organization_id)

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


def email_product_context(product_line: ProductLine | None) -> str:
    if product_line is None:
        return ""
    return " ".join(
        [product_line.name, product_line.description, *(product_line.product_keywords or [])]
    )


def email_contact_context(lead: Lead | None, contact: CRMContact | None) -> str:
    parts: list[str] = []
    if contact is not None and contact.name.strip():
        parts.append(contact.name.strip())
    if lead is not None and lead.company_name.strip():
        parts.append(lead.company_name.strip())
    return " ".join(parts)


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


BLOCKED_EMAIL_VERIFICATION_STATUSES = {"invalid", "spamtrap", "abuse", "do_not_mail"}


def normalized_email_verification_status(contact: CRMContact) -> str:
    return contact.email_verification_status.strip().lower().replace("-", "_")


def normalize_social_profiles(profiles: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for profile in profiles:
        platform = str(profile.get("platform", "")).strip()[:80]
        url = str(profile.get("url", "")).strip()[:1_000]
        if not platform or not url:
            continue
        key = (platform.lower(), url.lower().rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"platform": platform, "url": url})
    return normalized


def discovered_channel_keys(contact: DiscoveredContact) -> set[str]:
    keys: set[str] = set()
    if contact.email.strip():
        keys.add(f"email:{contact.email.strip().lower()}")
    if contact.phone.strip():
        keys.add(f"phone:{normalize_phone_key(contact.phone)}")
    if contact.linkedin_url.strip():
        keys.add(f"social:{normalize_url_key(contact.linkedin_url)}")
    if contact.whatsapp.strip():
        keys.add(f"whatsapp:{normalize_url_key(contact.whatsapp)}")
    for profile in normalize_social_profiles(contact.social_profiles):
        keys.add(f"social:{normalize_url_key(profile['url'])}")
    return {key for key in keys if not key.endswith(":")}


def crm_contact_channel_keys(contact: CRMContact) -> set[str]:
    discovered = DiscoveredContact(
        name=contact.name,
        title=contact.title,
        email=contact.email,
        phone=contact.phone,
        linkedin_url=contact.linkedin_url,
        whatsapp=contact.whatsapp,
        social_profiles=contact.social_profiles or [],
    )
    return discovered_channel_keys(discovered)


def find_matching_contact(
    contacts: list[CRMContact],
    discovered: DiscoveredContact,
) -> CRMContact | None:
    keys = discovered_channel_keys(discovered)
    return next((contact for contact in contacts if crm_contact_channel_keys(contact) & keys), None)


def merge_discovered_contact(contact: CRMContact, discovered: DiscoveredContact) -> bool:
    changed = False
    for field_name in ("email", "phone", "linkedin_url", "whatsapp", "source_url"):
        current = str(getattr(contact, field_name) or "").strip()
        incoming = str(getattr(discovered, field_name) or "").strip()
        if not current and incoming:
            setattr(contact, field_name, incoming)
            changed = True
    merged_profiles = normalize_social_profiles(
        [*(contact.social_profiles or []), *discovered.social_profiles]
    )
    if merged_profiles != (contact.social_profiles or []):
        contact.social_profiles = merged_profiles
        changed = True
    return changed


def normalize_phone_key(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def normalize_url_key(value: str) -> str:
    return value.strip().lower().rstrip("/")


def assert_contact_email_can_send(contact: CRMContact) -> None:
    status = normalized_email_verification_status(contact)
    if status in BLOCKED_EMAIL_VERIFICATION_STATUSES:
        raise ValueError(f"email verification blocks sending: {contact.email_verification_status}")


def website_from_email(email: str) -> str:
    parts = email.strip().rsplit("@", 1)
    if len(parts) != 2 or not parts[1].strip():
        raise ValueError("website or valid email domain is required")
    return normalize_website(parts[1])


def normalize_quote_line_items(items: list[dict[str, str | float | int]]) -> list[dict[str, str | float]]:
    normalized: list[dict[str, str | float]] = []
    for item in items:
        item_name = str(item.get("item_name", "")).strip()
        if not item_name:
            continue
        quantity = float(item.get("quantity", 0) or 0)
        unit_price = float(item.get("unit_price", 0) or 0)
        if quantity <= 0:
            raise ValueError("quote line quantity must be greater than zero")
        if unit_price < 0:
            raise ValueError("quote line unit price cannot be negative")
        normalized.append(
            {
                "item_name": item_name,
                "quantity": quantity,
                "unit_price": unit_price,
                "unit": str(item.get("unit", "")).strip() or "pcs",
                "notes": str(item.get("notes", "")).strip(),
            }
        )
    if not normalized:
        raise ValueError("at least one quote line item is required")
    return normalized


def quote_total(items: list[dict[str, str | float | int]]) -> float:
    total = 0.0
    for item in items:
        total += float(item.get("quantity", 0) or 0) * float(item.get("unit_price", 0) or 0)
    return total


OUTREACH_PRODUCT_TRANSLATIONS = (
    ("轴承", "industrial bearings"),
    ("照明", "LED lighting products"),
    ("led", "LED lighting products"),
    ("机械", "industrial machinery"),
    ("五金", "hardware products"),
)
OUTREACH_EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
GENERIC_CONTACT_TITLES = {"public website contact", "website contact"}


def build_email_subject(*, lead: Lead, product_line: ProductLine) -> str:
    product_phrase = outreach_product_phrase(product_line)
    company_name = outreach_company_name(lead.company_name)
    return f"{sentence_case(product_phrase)} supply discussion with {company_name}"


def build_email_body(
    *,
    lead: Lead,
    contact: CRMContact,
    product_line: ProductLine,
    evidence: list[LeadEvidence],
) -> str:
    del evidence  # Evidence remains in the draft snapshot for reviewers, not in the outbound email.
    product_phrase = outreach_product_phrase(product_line)
    company_name = outreach_company_name(lead.company_name)
    greeting = outreach_greeting(lead=lead, contact=contact)
    return (
        f"{greeting}\n\n"
        f"I am reaching out from our export team. We supply {product_phrase} for international "
        "buyers and distributors.\n\n"
        f"I came across {company_name} while researching companies in this sector. Based on your "
        f"public website, your business appears relevant to the {product_phrase} we supply.\n\n"
        "We would be glad to share our catalog, specifications, and quotation options for your "
        "review. If you are currently sourcing these products, could you let me know which types "
        "or specifications are most relevant to you?\n\n"
        "Best regards,\n"
        "Export Sales Team"
    )


def outreach_product_phrase(product_line: ProductLine) -> str:
    values = [
        product_line.name,
        product_line.description,
        *(product_line.product_keywords or []),
    ]
    searchable = " ".join(str(value) for value in values).lower()
    for keyword, translation in OUTREACH_PRODUCT_TRANSLATIONS:
        if keyword in searchable:
            return translation
    name = product_line.name.strip()
    return name if name and not contains_cjk(name) else "our product range"


def outreach_company_name(company_name: str) -> str:
    if contains_cjk(company_name):
        return "your company"
    words: list[str] = []
    for raw_word in company_name.strip().split():
        word = raw_word.strip(",.;:()[]")
        if not words or words[-1].lower() != word.lower():
            words.append(word)
    return " ".join(words) or "your company"


def outreach_greeting(*, lead: Lead, contact: CRMContact) -> str:
    name = contact.name.strip()
    email_local_part = contact.email.partition("@")[0].lower()
    is_generic = (
        not name
        or contains_cjk(name)
        or "@" in name
        or name.lower() == email_local_part
        or contact.title.strip().lower() in GENERIC_CONTACT_TITLES
    )
    if is_generic:
        company_name = outreach_company_name(lead.company_name)
        return "Hello," if company_name == "your company" else f"Hello {company_name} team,"
    return f"Dear {name},"


def sentence_case(value: str) -> str:
    return value[:1].upper() + value[1:]


def contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)
