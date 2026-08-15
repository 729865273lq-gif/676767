import asyncio

from app.agents.base.contracts import SearchResult
from app.agents.customer.agent import (
    CustomerDiscoveryService,
    build_discovery_queries,
    build_discovery_query,
    merge_discovery_results,
    product_relevance_terms,
    run_search_queries,
    search_result_matches_exclusions,
    search_result_matches_terms,
)
from app.agents.customer.models import CustomerDiscoveryInput
from app.crm.models import Lead, LeadBucket, LeadEvidence
from app.platform.models import ProductLine
from app.workflow.models import WorkflowRun, WorkflowState


class FakeSearchConnector:
    connector_id = "fake-search"
    version = "test"

    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.requests.append((query, limit))
        return [
            SearchResult(
                title="LumenHaus GmbH",
                url="https://www.lumenhaus.example/products",
                snippet="Commercial LED lighting distributor for retrofit projects.",
            )
        ]


class FakeFilteringSearchConnector:
    connector_id = "fake-filtering-search"
    version = "test"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                title="LumenHaus Distributor",
                url="https://lumenhaus.example",
                snippet="Industrial LED lighting importer and distributor.",
            ),
            SearchResult(
                title="Own Brand Factory",
                url="https://own-brand.example",
                snippet="Industrial LED lighting manufacturer.",
            ),
        ]


class PartiallyFailingSearchConnector:
    connector_id = "partially-failing-search"
    version = "test"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if "Berlin" in query:
            raise RuntimeError("temporary provider error")
        return [SearchResult(title=query, url=f"https://{len(query)}.example")]


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

    connector = FakeSearchConnector()
    output = asyncio.run(
        CustomerDiscoveryService(session, connector).start(
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
    assert output.lead_ids == [lead.id]
    assert output.query_count == 6
    assert output.candidate_count == 6
    assert output.duplicate_count == 5
    assert len(connector.requests) == 6
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


def test_customer_agent_filters_excluded_companies_before_persisting(
    session, organizations, members
) -> None:
    product_line = ProductLine(
        organization_id=organizations["acme"].id,
        name="Industrial LED Lighting",
        product_keywords=["industrial LED lighting"],
        buyer_profiles=["distributor"],
        target_regions=["Europe"],
        excluded_keywords=["own brand", "manufacturer"],
    )
    session.add(product_line)
    session.flush()

    output = asyncio.run(
        CustomerDiscoveryService(session, FakeFilteringSearchConnector()).start(
            actor_user_id=members["acme_member"].user_id,
            organization_id=organizations["acme"].id,
            payload=CustomerDiscoveryInput(
                product_line_id=product_line.id,
                target_market="Germany",
                buyer_profile="distributor",
            ),
            idempotency_key="customer-agent-filtering",
        )
    )

    assert output.lead_count == 1
    assert output.filtered_count == 1
    assert session.query(Lead).one().company_name == "LumenHaus Distributor"


def test_discovery_query_expands_chinese_product_buyer_and_market_terms() -> None:
    query = build_discovery_query(
        "轴承",
        ["轴承，轴承座"],
        CustomerDiscoveryInput(
            product_line_id="product-line-id",
            target_market="越南",
            buyer_profile="轴承生产，轴承销售，轴承批发商",
        ),
    )

    assert query == "bearing housing bearing manufacturer distributor wholesaler Vietnam"


def test_batch_query_plan_expands_bearing_buyers_and_malaysia_cities() -> None:
    queries = build_discovery_queries(
        "轴承",
        ["bearing housing", "pillow block bearing"],
        CustomerDiscoveryInput(
            product_line_id="product-line-id",
            target_market="马来西亚",
            buyer_profile="轴承销售，轴承批发商",
            limit=200,
        ),
    )

    assert len(queries) == 8
    assert queries[0] == "bearing distributor wholesaler Malaysia"
    assert any("pillow block bearing" in query for query in queries)
    assert any("Kuala Lumpur Malaysia" in query for query in queries)
    assert any("Selangor Malaysia" in query for query in queries)


def test_merge_discovery_results_dedupes_across_queries_and_keeps_contact_data() -> None:
    results, duplicate_count = merge_discovery_results(
        [
            (
                "bearing distributor Malaysia",
                [
                    SearchResult(
                        title="Alliance Bearings",
                        url="https://alliance.example/products",
                        snippet="Bearing distributor",
                    )
                ],
            ),
            (
                "bearing wholesaler Kuala Lumpur Malaysia",
                [
                    SearchResult(
                        title="Alliance Bearings Sdn Bhd",
                        url="https://www.alliance.example/contact",
                        email="sales@alliance.example",
                        phone="+60 3 1234 5678",
                    )
                ],
            ),
        ]
    )

    assert duplicate_count == 1
    assert len(results) == 1
    assert results[0].email == "sales@alliance.example"
    assert results[0].phone == "+60 3 1234 5678"


def test_batch_search_keeps_successful_queries_when_one_query_fails() -> None:
    batches = asyncio.run(
        run_search_queries(
            PartiallyFailingSearchConnector(),
            ["bearing distributor Germany", "bearing distributor Berlin Germany"],
            10,
        )
    )

    assert len(batches[0][1]) == 1
    assert batches[0][2] is None
    assert batches[1][1] == []
    assert str(batches[1][2]) == "temporary provider error"


def test_product_relevance_filter_rejects_unrelated_search_results() -> None:
    terms = product_relevance_terms(["bearing housing", "bearing"])

    assert search_result_matches_terms(
        SearchResult(
            title="Kian Ho Vietnam Bearings",
            url="https://example.com/bearings",
            snippet="Industrial bearing distributor",
        ),
        terms,
    )
    assert not search_result_matches_terms(
        SearchResult(
            title="Bamboo storage basket",
            url="https://example.com/basket",
            snippet="Handmade home storage product",
        ),
        terms,
    )


def test_customer_exclusion_filter_matches_company_summary_and_domain_case_insensitively() -> None:
    exclusions = ["competitor brand", "MANUFACTURER", "jobs"]

    assert search_result_matches_exclusions(
        SearchResult(
            title="Competitor Brand Vietnam",
            url="https://example.com",
            snippet="Industrial bearing distributor",
        ),
        exclusions,
    )
    assert search_result_matches_exclusions(
        SearchResult(
            title="Bearing supplier",
            url="https://factory-jobs.example.com",
            snippet="Manufacturer and recruitment portal",
        ),
        exclusions,
    )
    assert not search_result_matches_exclusions(
        SearchResult(
            title="Vietnam Bearing Distribution",
            url="https://buyer.example.com",
            snippet="Importer and wholesale buyer",
        ),
        exclusions,
    )
