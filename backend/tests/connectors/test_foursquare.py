import asyncio

import pytest

from app.connectors.search.foursquare import (
    FoursquareSearchConnector,
    FoursquareSearchError,
)


def test_foursquare_normalizes_contacts_and_social_profiles() -> None:
    requests: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def request_sender(
        endpoint: str, parameters: dict[str, str], headers: dict[str, str]
    ):
        requests.append((endpoint, parameters, headers))
        return {
            "results": [
                {
                    "fsq_place_id": "fsq-bearing-1",
                    "name": "Bearing Supply Malaysia",
                    "location": {
                        "formatted_address": "Kuala Lumpur, Malaysia"
                    },
                    "tel": "+60312345678",
                    "website": "bearings.example",
                    "categories": [{"name": "Industrial Equipment Supplier"}],
                    "social_media": {
                        "facebook_id": "bearing-supply",
                        "instagram": "@bearing_supply",
                        "twitter": "bearing_supply",
                    },
                    "placemaker_url": "https://foursquare.com/placemakers/review-place/fsq-bearing-1",
                }
            ]
        }

    result = asyncio.run(
        FoursquareSearchConnector(
            "fsq-key", request_sender, target_market="Malaysia"
        ).search("bearing distributor Malaysia", 10)
    )[0]

    assert requests[0][1] == {
        "query": "bearing distributor",
        "limit": "10",
        "sort": "RELEVANCE",
        "tel_format": "E164",
        "near": "Malaysia",
    }
    assert requests[0][2]["Authorization"] == "Bearer fsq-key"
    assert requests[0][2]["X-Places-Api-Version"] == "2025-06-17"
    assert result.url == "https://bearings.example"
    assert result.phone == "+60312345678"
    assert result.source_url.endswith("/fsq-bearing-1")
    assert {profile["platform"] for profile in result.social_profiles} == {
        "Facebook",
        "Instagram",
        "X",
    }


def test_foursquare_uses_stable_place_key_without_website() -> None:
    result = asyncio.run(
        FoursquareSearchConnector(
            "fsq-key",
            lambda *_: {
                "results": [
                    {"fsq_place_id": "fsq-bearing-2", "name": "Industrial Bearing"}
                ]
            },
        ).search("bearing", 1)
    )[0]

    assert result.canonical_key == "foursquare-place:fsq-bearing-2"
    assert result.url.endswith("/fsq-bearing-2")


def test_foursquare_rejects_empty_queries_and_invalid_results() -> None:
    connector = FoursquareSearchConnector("fsq-key", lambda *_: {"results": {}})

    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search("", 10))
    with pytest.raises(FoursquareSearchError, match="invalid results"):
        asyncio.run(connector.search("bearing", 10))
