import asyncio

import pytest

from app.agents.base.contracts import SearchResult
from app.connectors.search.multi import MultiSearchConnector, MultiSearchError


class FakeConnector:
    def __init__(self, connector_id: str, results: list[SearchResult] | None = None) -> None:
        self.connector_id = connector_id
        self.results = results or []
        self.requested_limits: list[int] = []

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.requested_limits.append(limit)
        return self.results[:limit]


class FailingConnector:
    connector_id = "failing"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        raise RuntimeError("provider unavailable")


def test_multi_search_connector_dedupes_results_across_sources() -> None:
    connector = MultiSearchConnector(
        [
            FakeConnector(
                "one",
                [
                    SearchResult(url="https://buyer.example/catalog", title="Buyer A", snippet="first"),
                    SearchResult(url="https://alpha.example", title="Alpha", snippet="alpha"),
                ],
            ),
            FakeConnector(
                "two",
                [
                    SearchResult(url="https://www.buyer.example/catalog/", title="Buyer A Copy", snippet="copy"),
                    SearchResult(url="https://beta.example", title="Beta", snippet="beta"),
                ],
            ),
        ]
    )

    results = asyncio.run(connector.search("lighting", 10))

    assert [item.url for item in results] == [
        "https://buyer.example/catalog",
        "https://alpha.example",
        "https://beta.example",
    ]


def test_multi_search_connector_gives_each_source_a_chance_before_limit() -> None:
    connector = MultiSearchConnector(
        [
            FakeConnector(
                "web",
                [
                    SearchResult(url="https://web-one.example", title="Web One"),
                    SearchResult(url="https://web-two.example", title="Web Two"),
                ],
            ),
            FakeConnector(
                "tomtom",
                [SearchResult(url="https://maps.example/place", title="Map Result")],
            ),
        ]
    )

    results = asyncio.run(connector.search("bearing distributor", 2))

    assert [item.title for item in results] == ["Web One", "Map Result"]


def test_multi_search_connector_limits_each_provider_request_for_batch_search() -> None:
    connectors = [FakeConnector(str(index)) for index in range(5)]
    connector = MultiSearchConnector(connectors)

    asyncio.run(connector.search("bearing distributor", 25))

    assert [item.requested_limits for item in connectors] == [[10], [10], [10], [10], [10]]


def test_multi_search_connector_keeps_successful_results_when_one_source_fails() -> None:
    connector = MultiSearchConnector(
        [
            FailingConnector(),
            FakeConnector("working", [SearchResult(url="https://buyer.example", title="Buyer", snippet="")]),
        ]
    )

    results = asyncio.run(connector.search("lighting", 10))

    assert [item.title for item in results] == ["Buyer"]


def test_multi_search_connector_raises_when_every_source_fails() -> None:
    connector = MultiSearchConnector([FailingConnector()])

    with pytest.raises(MultiSearchError, match="provider unavailable"):
        asyncio.run(connector.search("lighting", 10))
