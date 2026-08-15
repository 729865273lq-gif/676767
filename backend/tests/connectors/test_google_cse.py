import asyncio

import pytest

from app.connectors.search.google_cse import (
    GOOGLE_CSE_ENDPOINT,
    GoogleProgrammableSearchConnector,
    GoogleProgrammableSearchError,
)


def test_google_cse_connector_normalizes_results_and_sends_expected_params() -> None:
    requests: list[tuple[str, dict[str, str | int]]] = []

    def request_sender(endpoint: str, params: dict[str, str | int]) -> dict:
        requests.append((endpoint, params))
        return {
            "items": [
                {
                    "title": "Lighting Distributor",
                    "link": "https://buyer.example/catalog",
                    "snippet": "Industrial lighting buyer and distributor.",
                }
            ]
        }

    results = asyncio.run(
        GoogleProgrammableSearchConnector("google-key", "engine-id", request_sender).search(
            "LED distributors Germany",
            10,
        )
    )

    assert results[0].title == "Lighting Distributor"
    assert results[0].url == "https://buyer.example/catalog"
    assert results[0].snippet == "Industrial lighting buyer and distributor."
    assert requests == [
        (
            GOOGLE_CSE_ENDPOINT,
            {
                "key": "google-key",
                "cx": "engine-id",
                "q": "LED distributors Germany",
                "num": 10,
                "start": 1,
            },
        )
    ]


def test_google_cse_connector_paginates_to_requested_limit() -> None:
    starts: list[int] = []

    def request_sender(_endpoint: str, params: dict[str, str | int]) -> dict:
        starts.append(int(params["start"]))
        page_index = len(starts)
        return {
            "items": [
                {
                    "title": f"Buyer {page_index}-{item}",
                    "link": f"https://buyer-{page_index}-{item}.example",
                    "snippet": "buyer",
                }
                for item in range(10)
            ]
        }

    results = asyncio.run(
        GoogleProgrammableSearchConnector("google-key", "engine-id", request_sender).search("LED", 12)
    )

    assert len(results) == 12
    assert starts == [1, 11]


def test_google_cse_connector_rejects_empty_queries_and_invalid_items() -> None:
    connector = GoogleProgrammableSearchConnector("google-key", "engine-id", lambda *_: {"items": {}})

    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search(" ", 10))
    with pytest.raises(GoogleProgrammableSearchError, match="invalid items"):
        asyncio.run(connector.search("lighting", 10))
