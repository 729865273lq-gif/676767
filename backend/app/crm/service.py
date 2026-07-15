from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base.contracts import SearchResult
from app.crm.models import Lead, LeadBucket, LeadEvidence
from app.crm.scoring import LeadQualification


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

    def evidence_for_lead(self, lead_id: str) -> list[LeadEvidence]:
        return list(
            self.session.scalars(
                select(LeadEvidence)
                .where(LeadEvidence.lead_id == lead_id)
                .order_by(LeadEvidence.captured_at)
            )
        )


def canonical_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        raise ValueError("search result must contain an absolute website URL")
    return domain
