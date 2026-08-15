import asyncio

import pytest

from app.connectors.search.tomtom import TomTomSearchConnector, TomTomSearchError


def test_tomtom_normalizes_business_contact_fields() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def request_sender(endpoint: str, parameters: dict[str, str]):
        requests.append((endpoint, parameters))
        return {
            "results": [
                {
                    "type": "POI",
                    "id": "tomtom-place-1",
                    "poi": {
                        "name": "Bearing Supply Malaysia",
                        "phone": "+60 3 1234 5678",
                        "url": "www.bearings.example/products",
                        "categories": ["bearing supplier", "industrial equipment"],
                    },
                    "address": {"freeformAddress": "Kuala Lumpur, Malaysia"},
                    "position": {"lat": 3.139, "lon": 101.6869},
                }
            ]
        }

    results = asyncio.run(
        TomTomSearchConnector("tomtom-key", request_sender).search(
            "bearing distributor Malaysia", 10
        )
    )

    assert requests[0][0].endswith("/bearing%20distributor%20Malaysia.json")
    assert requests[0][1] == {
        "key": "tomtom-key",
        "limit": "10",
        "typeahead": "false",
        "language": "en-US",
    }
    assert results[0].title == "Bearing Supply Malaysia"
    assert results[0].url == "https://www.bearings.example/products"
    assert results[0].phone == "+60 3 1234 5678"
    assert results[0].source_url == "https://www.bearings.example/products"
    assert "Kuala Lumpur" in results[0].snippet
    assert "bearing supplier" in results[0].snippet


def test_tomtom_uses_stable_place_key_when_business_has_no_website() -> None:
    connector = TomTomSearchConnector(
        "tomtom-key",
        lambda *_: {
            "results": [
                {
                    "id": "place-without-website",
                    "poi": {"name": "Industrial Buyer", "categories": ["company"]},
                    "address": {"freeformAddress": "Penang, Malaysia"},
                }
            ]
        },
    )

    result = asyncio.run(connector.search("industrial buyer Penang", 1))[0]

    assert result.canonical_key == "tomtom-place:place-without-website"
    assert result.url == "https://www.tomtom.com/maps"


def test_tomtom_rejects_empty_queries_and_invalid_results() -> None:
    connector = TomTomSearchConnector("tomtom-key", lambda *_: {"results": {}})

    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search("", 10))
    with pytest.raises(TomTomSearchError, match="invalid results"):
        asyncio.run(connector.search("bearing", 10))
