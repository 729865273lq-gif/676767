import asyncio

import pytest

from app.connectors.search.google_places import (
    GOOGLE_PLACES_ENDPOINT,
    GOOGLE_PLACES_FIELD_MASK,
    GooglePlacesSearchConnector,
    GooglePlacesSearchError,
)


def test_google_places_normalizes_business_contact_fields() -> None:
    requests: list[tuple[str, dict, str, str]] = []

    def request_sender(endpoint: str, payload: dict, api_key: str, field_mask: str) -> dict:
        requests.append((endpoint, payload, api_key, field_mask))
        return {
            "places": [
                {
                    "id": "place-123",
                    "displayName": {"text": "Berlin Lighting GmbH"},
                    "formattedAddress": "Berlin, Germany",
                    "websiteUri": "https://berlin-lighting.example",
                    "internationalPhoneNumber": "+49 30 123456",
                    "primaryType": "wholesaler",
                    "businessStatus": "OPERATIONAL",
                    "googleMapsUri": "https://maps.google.com/?cid=123",
                }
            ]
        }

    results = asyncio.run(
        GooglePlacesSearchConnector("places-key", request_sender).search(
            "LED lighting distributors Berlin",
            10,
        )
    )

    assert results[0].title == "Berlin Lighting GmbH"
    assert results[0].url == "https://berlin-lighting.example"
    assert results[0].phone == "+49 30 123456"
    assert results[0].source_url == "https://maps.google.com/?cid=123"
    assert "Berlin, Germany" in results[0].snippet
    assert requests == [
        (
            GOOGLE_PLACES_ENDPOINT,
            {
                "textQuery": "LED lighting distributors Berlin",
                "pageSize": 10,
                "includePureServiceAreaBusinesses": True,
                "languageCode": "en",
            },
            "places-key",
            GOOGLE_PLACES_FIELD_MASK,
        )
    ]


def test_google_places_uses_place_key_when_business_has_no_website() -> None:
    connector = GooglePlacesSearchConnector(
        "places-key",
        lambda *_: {
            "places": [
                {
                    "id": "place-456",
                    "displayName": {"text": "Map Only Buyer"},
                    "nationalPhoneNumber": "030 7654321",
                    "googleMapsUri": "https://maps.google.com/?cid=456",
                }
            ]
        },
    )

    result = asyncio.run(connector.search("buyer", 1))[0]

    assert result.url == "https://maps.google.com/?cid=456"
    assert result.canonical_key == "google-place:place-456"
    assert result.phone == "030 7654321"


def test_google_places_rejects_empty_queries_and_invalid_places() -> None:
    connector = GooglePlacesSearchConnector("places-key", lambda *_: {"places": {}})

    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search(" ", 10))
    with pytest.raises(GooglePlacesSearchError, match="invalid places"):
        asyncio.run(connector.search("lighting", 10))
