from datetime import UTC, datetime

from app.agents.base.contracts import SearchResult
from app.crm.models import Lead, LeadBucket
from app.crm.scoring import LeadQualification
from app.crm.service import LeadService
from app.platform.models import ProductLine
from app.workflow.models import WorkflowRun


def test_list_leads_returns_most_recently_discovered_first(session, organizations) -> None:
    organization = organizations["acme"]
    product_line = ProductLine(organization_id=organization.id, name="Industrial Bearings")
    workflow_run = WorkflowRun(
        organization_id=organization.id,
        agent_id="customer",
        agent_version="test",
        input_json={},
        idempotency_key="lead-ordering-test",
    )
    session.add_all([product_line, workflow_run])
    session.flush()

    older = Lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        company_name="Older Company",
        website="https://older.example",
        canonical_domain="older.example",
        target_market="Malaysia",
        score=95,
        bucket=LeadBucket.PRIORITY_RECOMMENDATION,
        last_discovered_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    newer = Lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        company_name="Newer Company",
        website="https://newer.example",
        canonical_domain="newer.example",
        target_market="Malaysia",
        score=40,
        bucket=LeadBucket.NEEDS_ENRICHMENT,
        last_discovered_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    session.add_all([older, newer])
    session.flush()

    leads = LeadService(session).list_leads(organization_id=organization.id)

    assert [lead.company_name for lead in leads] == ["Newer Company", "Older Company"]


def test_list_leads_uses_creation_time_for_equal_discovery_time(session, organizations) -> None:
    organization = organizations["acme"]
    product_line = ProductLine(organization_id=organization.id, name="Industrial Bearings")
    workflow_run = WorkflowRun(
        organization_id=organization.id,
        agent_id="customer",
        agent_version="test",
        input_json={},
        idempotency_key="lead-created-ordering-test",
    )
    session.add_all([product_line, workflow_run])
    session.flush()

    discovery_time = datetime(2026, 8, 13, 8, tzinfo=UTC)
    session.add_all(
        [
            Lead(
                organization_id=organization.id,
                workflow_run_id=workflow_run.id,
                product_line_id=product_line.id,
                company_name="Added First",
                website="https://added-first.example",
                canonical_domain="added-first.example",
                target_market="Malaysia",
                score=60,
                bucket=LeadBucket.NEEDS_ENRICHMENT,
                last_discovered_at=discovery_time,
                created_at=datetime(2026, 8, 13, 8, 1, tzinfo=UTC),
            ),
            Lead(
                organization_id=organization.id,
                workflow_run_id=workflow_run.id,
                product_line_id=product_line.id,
                company_name="Added Last",
                website="https://added-last.example",
                canonical_domain="added-last.example",
                target_market="Malaysia",
                score=60,
                bucket=LeadBucket.NEEDS_ENRICHMENT,
                last_discovered_at=discovery_time,
                created_at=datetime(2026, 8, 13, 8, 2, tzinfo=UTC),
            ),
        ]
    )
    session.flush()

    leads = LeadService(session).list_leads(organization_id=organization.id)

    assert [lead.company_name for lead in leads] == ["Added Last", "Added First"]


def test_rediscovered_lead_refreshes_last_discovered_at(session, organizations) -> None:
    organization = organizations["acme"]
    product_line = ProductLine(organization_id=organization.id, name="Industrial Bearings")
    workflow_run = WorkflowRun(
        organization_id=organization.id,
        agent_id="customer",
        agent_version="test",
        input_json={},
        idempotency_key="lead-rediscovery-test",
    )
    session.add_all([product_line, workflow_run])
    session.flush()
    old_discovery_time = datetime(2026, 8, 9, tzinfo=UTC)
    lead = Lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        company_name="Rediscovered Company",
        website="https://rediscovered.example",
        canonical_domain="rediscovered.example",
        target_market="Malaysia",
        score=60,
        bucket=LeadBucket.NEEDS_ENRICHMENT,
        last_discovered_at=old_discovery_time,
    )
    session.add(lead)
    session.flush()

    rediscovered = LeadService(session).save_discovered_lead(
        organization_id=organization.id,
        workflow_run_id=workflow_run.id,
        product_line_id=product_line.id,
        target_market="Malaysia",
        buyer_profile="Distributor",
        result=SearchResult(
            url="https://rediscovered.example/products",
            title="Rediscovered Company",
            snippet="Bearing distributor",
            canonical_key="rediscovered.example",
        ),
        qualification=LeadQualification(
            bucket=LeadBucket.NEEDS_ENRICHMENT,
            score=60,
            reasons=["product fit"],
            missing_signals=["email"],
        ),
    )

    assert rediscovered.id == lead.id
    assert rediscovered.last_discovered_at > old_discovery_time
