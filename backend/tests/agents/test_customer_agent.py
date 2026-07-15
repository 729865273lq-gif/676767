import asyncio

from app.agents.base.contracts import SearchResult
from app.agents.customer.agent import CustomerDiscoveryService
from app.agents.customer.models import CustomerDiscoveryInput
from app.crm.models import Lead, LeadBucket, LeadEvidence
from app.platform.models import ProductLine
from app.workflow.models import WorkflowRun, WorkflowState


class FakeSearchConnector:
    connector_id = "fake-search"
    version = "test"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        assert query == "industrial LED lighting distributor Germany"
        assert limit == 20
        return [
            SearchResult(
                title="LumenHaus GmbH",
                url="https://www.lumenhaus.example/products",
                snippet="Commercial LED lighting distributor for retrofit projects.",
            )
        ]


def test_customer_agent_persists_evidence_backed_lead_needing_enrichment(
    session, organizations, members
) -> None:
    product_line = ProductLine(
        organization_id=organizations["acme"].id,
        name="Industrial LED Lighting",
        product_keywords=["industrial LED lighting"],
        buyer_profiles=["distributor"],
        target_regions=["Europe"],
    )
    session.add(product_line)
    session.flush()

    output = asyncio.run(
        CustomerDiscoveryService(session, FakeSearchConnector()).start(
            actor_user_id=members["acme_member"].user_id,
            organization_id=organizations["acme"].id,
            payload=CustomerDiscoveryInput(
                product_line_id=product_line.id,
                target_market="Germany",
                buyer_profile="distributor",
            ),
            idempotency_key="customer-agent-germany-1",
        )
    )

    lead = session.query(Lead).one()
    evidence = session.query(LeadEvidence).one()
    workflow_run = session.query(WorkflowRun).one()

    assert output.lead_count == 1
    assert lead.canonical_domain == "lumenhaus.example"
    assert lead.bucket == LeadBucket.NEEDS_ENRICHMENT
    assert "usable contact channel" in lead.missing_signals
    assert evidence.source_url == lead.website
    assert workflow_run.state == WorkflowState.COMPLETED


def test_customer_agent_reuses_completed_run_for_same_idempotency_key(
    session, organizations, members
) -> None:
    product_line = ProductLine(
        organization_id=organizations["acme"].id,
        name="Industrial LED Lighting",
        product_keywords=["industrial LED lighting"],
    )
    session.add(product_line)
    session.flush()
    service = CustomerDiscoveryService(session, FakeSearchConnector())
    payload = CustomerDiscoveryInput(
        product_line_id=product_line.id,
        target_market="Germany",
        buyer_profile="distributor",
    )

    first = asyncio.run(
        service.start(
            actor_user_id=members["acme_member"].user_id,
            organization_id=organizations["acme"].id,
            payload=payload,
            idempotency_key="customer-agent-idempotent",
        )
    )
    second = asyncio.run(
        service.start(
            actor_user_id=members["acme_member"].user_id,
            organization_id=organizations["acme"].id,
            payload=payload,
            idempotency_key="customer-agent-idempotent",
        )
    )

    assert first == second
    assert session.query(WorkflowRun).count() == 1
