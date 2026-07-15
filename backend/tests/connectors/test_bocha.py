import asyncio
import json

import pytest

from app.connectors.search.bocha import BOCHA_WEB_SEARCH_ENDPOINT, BochaSearchConnector, BochaSearchError


def test_bocha_connector_normalizes_public_web_results() -> None:
    requests: list[tuple[str, bytes, str]] = []

    def request_sender(endpoint: str, payload: bytes, api_key: str) -> dict:
        requests.append((endpoint, payload, api_key))
        return {
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "Example Lighting Distributor",
                            "url": "https://buyer.example/products",
                            "summary": "Commercial LED lighting distributor.",
                        }
                    ]
                }
            }
        }

    results = asyncio.run(
        BochaSearchConnector("bocha-test-key", request_sender).search("LED distributors Germany", 10)
    )

    assert results[0].title == "Example Lighting Distributor"
    assert results[0].url == "https://buyer.example/products"
    assert json.loads(requests[0][1]) == {
        "query": "LED distributors Germany",
        "count": 10,
        "summary": True,
    }
    assert requests[0][0] == BOCHA_WEB_SEARCH_ENDPOINT
    assert requests[0][2] == "bocha-test-key"


def test_bocha_connector_rejects_empty_queries_and_invalid_provider_data() -> None:
    connector = BochaSearchConnector("bocha-test-key", lambda *_: {"data": {}})

    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search(" ", 10))
    with pytest.raises(BochaSearchError, match="web pages"):
        asyncio.run(connector.search("lighting", 10))
