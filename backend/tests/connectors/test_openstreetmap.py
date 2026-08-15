import asyncio

import pytest

from app.connectors.search.openstreetmap import (
    OPENSTREETMAP_SEARCH_ENDPOINT,
    OVERPASS_ENDPOINTS,
    OpenStreetMapSearchConnector,
    OpenStreetMapSearchError,
)


def test_openstreetmap_normalizes_business_and_contact_tags() -> None:
    requests: list[tuple[str, dict[str, str | int]]] = []

    def request_sender(endpoint: str, params: dict[str, str | int]) -> list[dict]:
        requests.append((endpoint, params))
        return [
            {
                "osm_type": "node",
                "osm_id": 123,
                "category": "shop",
                "type": "lighting",
                "display_name": "Berlin Light GmbH, Berlin, Germany",
                "namedetails": {"name": "Berlin Light GmbH"},
                "extratags": {
                    "website": "berlin-light.example",
                    "contact:phone": "+49 30 123456",
                    "contact:email": "sales@berlin-light.example",
                    "contact:instagram": "https://instagram.com/berlinlight",
                },
            },
            {
                "osm_type": "relation",
                "osm_id": 999,
                "category": "boundary",
                "type": "administrative",
                "display_name": "Berlin, Germany",
                "namedetails": {"name": "Berlin"},
            },
        ]

    results = asyncio.run(
        OpenStreetMapSearchConnector(request_sender).search("lighting distributor Berlin", 10)
    )

    assert len(results) == 1
    assert results[0].title == "Berlin Light GmbH"
    assert results[0].url == "https://berlin-light.example"
    assert results[0].email == "sales@berlin-light.example"
    assert results[0].phone == "+49 30 123456"
    assert results[0].social_profiles == [
        {"platform": "Instagram", "url": "https://instagram.com/berlinlight"}
    ]
    assert results[0].source_url == "https://www.openstreetmap.org/node/123"
    assert requests[0][0] == OPENSTREETMAP_SEARCH_ENDPOINT
    assert requests[0][1]["extratags"] == 1


def test_openstreetmap_uses_stable_osm_key_without_website() -> None:
    connector = OpenStreetMapSearchConnector(
        lambda *_: [
            {
                "osm_type": "way",
                "osm_id": 456,
                "category": "office",
                "type": "company",
                "display_name": "Map Buyer, Madrid, Spain",
                "extratags": {"phone": "+34 91 555 0101"},
            }
        ]
    )

    result = asyncio.run(connector.search("buyer Madrid", 1))[0]

    assert result.url == "https://www.openstreetmap.org/way/456"
    assert result.canonical_key == "osm:way:456"


def test_openstreetmap_uses_target_area_and_overpass_for_b2b_queries() -> None:
    area_requests: list[str] = []
    overpass_requests: list[tuple[str, str]] = []

    def area_resolver(target_market: str) -> int:
        area_requests.append(target_market)
        return 3_600_000_001

    def overpass_sender(endpoint: str, query: str) -> dict:
        overpass_requests.append((endpoint, query))
        return {
            "elements": [
                {
                    "type": "node",
                    "id": 789,
                    "tags": {
                        "name": "Lumen Trade GmbH",
                        "shop": "lighting",
                        "website": "https://lumen-trade.example",
                        "phone": "+49 30 998877",
                        "contact:facebook": "https://facebook.com/lumentrade",
                        "addr:city": "Berlin",
                        "addr:country": "DE",
                    },
                }
            ]
        }

    connector = OpenStreetMapSearchConnector(
        target_market="Germany",
        area_resolver=area_resolver,
        overpass_sender=overpass_sender,
    )
    result = asyncio.run(connector.search("LED floodlight distributor Germany", 5))[0]

    assert area_requests == ["Germany"]
    assert "area(3600000001)" in overpass_requests[0][1]
    assert 'shop"~"electrical|lighting' in overpass_requests[0][1]
    assert 'office"~"company|logistics' not in overpass_requests[0][1]
    assert result.title == "Lumen Trade GmbH"
    assert result.phone == "+49 30 998877"
    assert result.social_profiles == [
        {"platform": "Facebook", "url": "https://facebook.com/lumentrade"}
    ]


def test_openstreetmap_rejects_empty_queries_and_invalid_responses() -> None:
    connector = OpenStreetMapSearchConnector(lambda *_: [])
    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search(" ", 10))

    def invalid_sender(*_args) -> list[dict]:
        raise OpenStreetMapSearchError("invalid response")

    with pytest.raises(OpenStreetMapSearchError, match="invalid response"):
        asyncio.run(OpenStreetMapSearchConnector(invalid_sender).search("buyer", 10))


def test_openstreetmap_fails_over_between_public_overpass_instances() -> None:
    attempted_endpoints: list[str] = []

    def overpass_sender(endpoint: str, _query: str) -> dict:
        attempted_endpoints.append(endpoint)
        if endpoint == OVERPASS_ENDPOINTS[0]:
            raise OpenStreetMapSearchError("primary timed out")
        return {
            "elements": [
                {
                    "type": "node",
                    "id": 321,
                    "tags": {"name": "Backup Result", "shop": "lighting"},
                }
            ]
        }

    connector = OpenStreetMapSearchConnector(
        target_market="Germany",
        area_resolver=lambda _target: 3_600_000_001,
        overpass_sender=overpass_sender,
    )

    results = asyncio.run(connector.search("LED lighting", 5))

    assert attempted_endpoints == list(OVERPASS_ENDPOINTS[:2])
    assert results[0].title == "Backup Result"


def test_openstreetmap_translates_chinese_target_market_for_area_lookup() -> None:
    resolved_markets: list[str] = []

    connector = OpenStreetMapSearchConnector(
        target_market="越南",
        area_resolver=lambda market: resolved_markets.append(market) or 3_600_049_915,
        overpass_sender=lambda _endpoint, _query: {"elements": []},
    )

    asyncio.run(connector.search("bearing manufacturer Vietnam", 5))

    assert resolved_markets == ["Vietnam"]
