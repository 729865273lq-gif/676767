import asyncio

import pytest

from app.connectors.search.geoapify import GeoapifySearchConnector, GeoapifySearchError


def test_geoapify_fetches_place_details_and_normalizes_contacts() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def request_sender(endpoint: str, parameters: dict[str, str]):
        requests.append((endpoint, parameters))
        if endpoint.endswith("/geocode/search"):
            return {
                "results": [
                    {
                        "place_id": "geo-place-1",
                        "name": "Bearing Supply Malaysia",
                        "formatted": "Kuala Lumpur, Malaysia",
                        "categories": ["commercial.trade"],
                    }
                ]
            }
        return {
            "features": [
                {
                    "properties": {
                        "feature_type": "details",
                        "place_id": "geo-place-1",
                        "name": "Bearing Supply Malaysia",
                        "website": "bearings.example",
                        "contact": {
                            "phone": "+60 3 1234 5678",
                            "email": "sales@bearings.example",
                        },
                    }
                }
            ]
        }

    result = asyncio.run(
        GeoapifySearchConnector("geo-key", request_sender).search(
            "bearing distributor Malaysia", 10
        )
    )[0]

    assert requests[0][1]["text"] == "bearing Malaysia"
    assert requests[0][1]["apiKey"] == "geo-key"
    assert requests[1][1]["id"] == "geo-place-1"
    assert result.title == "Bearing Supply Malaysia"
    assert result.url == "https://bearings.example"
    assert result.phone == "+60 3 1234 5678"
    assert result.email == "sales@bearings.example"


def test_geoapify_falls_back_to_business_categories_in_target_market() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def request_sender(endpoint: str, parameters: dict[str, str]):
        requests.append((endpoint, parameters))
        if endpoint.endswith("/geocode/search") and parameters["text"].startswith("bearing"):
            return {"results": []}
        if endpoint.endswith("/geocode/search"):
            return {"results": [{"place_id": "market-malaysia"}]}
        if endpoint.endswith("/places"):
            return {
                "features": [
                    {
                        "properties": {
                            "place_id": "geo-place-2",
                            "name": "Industrial Bearing Trading",
                            "formatted": "Penang, Malaysia",
                            "categories": ["commercial.trade"],
                        }
                    }
                ]
            }
        return {
            "features": [
                {
                    "properties": {
                        "feature_type": "details",
                        "place_id": "geo-place-2",
                        "name": "Industrial Bearing Trading",
                    }
                }
            ]
        }

    results = asyncio.run(
        GeoapifySearchConnector(
            "geo-key", request_sender, target_market="Malaysia"
        ).search("bearing distributor Malaysia", 5)
    )

    places_request = next(item for item in requests if item[0].endswith("/places"))
    assert places_request[1]["filter"] == "place:market-malaysia"
    assert "production" in places_request[1]["categories"]
    assert results[0].canonical_key == "geoapify-place:geo-place-2"


def test_geoapify_rejects_empty_queries_and_invalid_results() -> None:
    connector = GeoapifySearchConnector("geo-key", lambda *_: {"results": {}})

    with pytest.raises(ValueError, match="query"):
        asyncio.run(connector.search("", 10))
    with pytest.raises(GeoapifySearchError, match="invalid results"):
        asyncio.run(connector.search("bearing", 10))


def test_geoapify_keeps_place_when_details_request_fails() -> None:
    def request_sender(endpoint: str, _parameters: dict[str, str]):
        if endpoint.endswith("/geocode/search"):
            return {
                "results": [
                    {
                        "place_id": "geo-place-3",
                        "name": "Bearing Manufacturer",
                        "formatted": "Selangor, Malaysia",
                    }
                ]
            }
        raise GeoapifySearchError("temporary provider failure")

    result = asyncio.run(
        GeoapifySearchConnector("geo-key", request_sender).search("bearing Malaysia", 5)
    )[0]

    assert result.title == "Bearing Manufacturer"
    assert result.canonical_key == "geoapify-place:geo-place-3"
