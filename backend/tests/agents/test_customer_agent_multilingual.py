import asyncio

from app.agents.base.contracts import SearchResult
from app.agents.customer.agent import CustomerDiscoveryService, build_discovery_queries
from app.agents.customer.models import CustomerDiscoveryInput
from app.platform.models import ProductLine
from app.platform.search_keywords import (
    KeywordPlan,
    build_search_keyword_provider,
    latin_keywords,
)


class FakeChatConnector:
    def __init__(self, responses=None, default='{"keywords": ["translated keyword"]}'):
        self.responses = list(responses) if responses is not None else []
        self.default = default
        self.calls: list[str] = []

    def chat_text(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return self.default


class FakeSearchConnector:
    connector_id = "fake-search"
    version = "test"

    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.requests.append((query, limit))
        return [
            SearchResult(
                title="LagerHaus GmbH",
                url="https://lagerhaus.example",
                snippet="Industrial bearing distributor.",
            )
        ]


def test_build_queries_expands_localized_and_english_keywords() -> None:
    plan = KeywordPlan(
        language="de",
        localized=["led flutlicht", "lagerhallenbeleuchtung"],
        english=["LED floodlight", "industrial lighting"],
    )
    queries = build_discovery_queries(
        "工业 LED 照明",
        ["LED 投光灯", "仓库照明"],
        CustomerDiscoveryInput(product_line_id="p", target_market="Germany", limit=200),
        keyword_plan=plan,
    )

    assert any("led flutlicht" in query for query in queries)
    assert any("lagerhallenbeleuchtung" in query for query in queries)
    assert any("LED floodlight" in query for query in queries)
    assert any("industrial lighting" in query for query in queries)


def test_build_queries_without_plan_preserves_original_behavior() -> None:
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


def test_build_queries_skips_cjk_only_keywords_when_localized_exist() -> None:
    plan = KeywordPlan(language="de", localized=["lager"], english=["bearing"])
    queries = build_discovery_queries(
        "轴承",
        ["轴承", "轴承座"],
        CustomerDiscoveryInput(product_line_id="p", target_market="Germany", limit=200),
        keyword_plan=plan,
    )

    assert not any("轴承" in query for query in queries)
    assert not any("轴承座" in query for query in queries)


def test_latin_keywords_drops_cjk_only_keywords() -> None:
    assert latin_keywords(["轴承", "bearing housing", "轴承座"]) == ["bearing housing"]
    assert latin_keywords(["轴承", "轴承座"]) == []


def test_agent_uses_keyword_provider_when_country_resolves(session, organizations, members) -> None:
    product_line = ProductLine(
        organization_id=organizations["acme"].id,
        name="工业 LED 照明",
        product_keywords=["LED 投光灯"],
        buyer_profiles=["distributor"],
    )
    session.add(product_line)
    session.flush()

    provider = build_search_keyword_provider(FakeChatConnector())
    connector = FakeSearchConnector()
    output = asyncio.run(
        CustomerDiscoveryService(session, connector, keyword_provider=provider).start(
            actor_user_id=members["acme_member"].user_id,
            organization_id=organizations["acme"].id,
            payload=CustomerDiscoveryInput(
                product_line_id=product_line.id,
                target_market="Germany",
                location_country_code="DE",
                limit=20,
            ),
            idempotency_key="multilingual-germany-1",
        )
    )

    assert any("translated keyword" in query for query in output.queries)


def test_agent_keeps_original_queries_when_country_missing(session, organizations, members) -> None:
    product_line = ProductLine(
        organization_id=organizations["acme"].id,
        name="轴承",
        product_keywords=["bearing"],
        buyer_profiles=["distributor"],
    )
    session.add(product_line)
    session.flush()

    provider = build_search_keyword_provider(FakeChatConnector())
    output = asyncio.run(
        CustomerDiscoveryService(session, FakeSearchConnector(), keyword_provider=provider).start(
            actor_user_id=members["acme_member"].user_id,
            organization_id=organizations["acme"].id,
            payload=CustomerDiscoveryInput(
                product_line_id=product_line.id,
                target_market="Germany",
                buyer_profile="distributor",
                limit=20,
            ),
            idempotency_key="original-germany-1",
        )
    )

    assert output.query_count == 4
    assert all("translated keyword" not in query for query in output.queries)
