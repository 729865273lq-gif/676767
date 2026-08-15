from __future__ import annotations

import asyncio
import json
import re
import ssl
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import truststore

from app.agents.base.contracts import SearchResult

GEOAPIFY_GEOCODING_ENDPOINT = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_PLACES_ENDPOINT = "https://api.geoapify.com/v2/places"
GEOAPIFY_PLACE_DETAILS_ENDPOINT = "https://api.geoapify.com/v2/place-details"
GEOAPIFY_MAP_URL = "https://www.geoapify.com/"

RequestSender = Callable[[str, dict[str, str]], dict[str, Any]]


class GeoapifySearchError(RuntimeError):
    """Raised when Geoapify cannot return normalized place results."""


class GeoapifySearchConnector:
    connector_id = "geoapify"
    version = "v2"

    def __init__(
        self,
        api_key: str,
        request_sender: RequestSender | None = None,
        *,
        target_market: str = "",
    ) -> None:
        if not api_key.strip():
            raise ValueError("Geoapify API key is required")
        self._api_key = api_key.strip()
        self._request_sender = request_sender or _get_json
        self._target_market = target_market.strip()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        count = min(max(limit, 1), 40)
        provider_query = _provider_query(query.strip(), self._target_market)
        candidates = await asyncio.to_thread(
            self._request_sender,
            GEOAPIFY_GEOCODING_ENDPOINT,
            {
                "text": provider_query,
                "format": "json",
                "type": "amenity",
                "lang": "en",
                "limit": str(count),
                "apiKey": self._api_key,
            },
        )
        rows = _unique_place_rows(_geocoding_rows(candidates))

        if not rows and self._target_market:
            rows = _unique_place_rows(
                await self._search_business_categories(self._target_market, count)
            )

        results: list[SearchResult] = []
        for row in rows[:count]:
            place_id = _string(row.get("place_id"))
            details = row
            if place_id:
                try:
                    response = await asyncio.to_thread(
                        self._request_sender,
                        GEOAPIFY_PLACE_DETAILS_ENDPOINT,
                        {
                            "id": place_id,
                            "features": "details",
                            "lang": "en",
                            "apiKey": self._api_key,
                        },
                    )
                except GeoapifySearchError:
                    response = {}
                details = row | _detail_properties(response)
            normalized = _normalize_result(details)
            if normalized is not None:
                results.append(normalized)
        return results[:count]

    async def _search_business_categories(
        self, target_market: str, limit: int
    ) -> list[dict[str, Any]]:
        location_response = await asyncio.to_thread(
            self._request_sender,
            GEOAPIFY_GEOCODING_ENDPOINT,
            {
                "text": target_market,
                "format": "json",
                "lang": "en",
                "limit": "1",
                "apiKey": self._api_key,
            },
        )
        locations = _geocoding_rows(location_response)
        place_id = _string(locations[0].get("place_id")) if locations else ""
        if not place_id:
            return []
        response = await asyncio.to_thread(
            self._request_sender,
            GEOAPIFY_PLACES_ENDPOINT,
            {
                "categories": "office.company,production,commercial.trade",
                "filter": f"place:{place_id}",
                "lang": "en",
                "limit": str(limit),
                "apiKey": self._api_key,
            },
        )
        return _feature_rows(response)


def _get_json(endpoint: str, parameters: dict[str, str]) -> dict[str, Any]:
    request = Request(
        f"{endpoint}?{urlencode(parameters)}",
        headers={"Accept": "application/json", "User-Agent": "TradeAxis/1.0"},
    )
    try:
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(request, timeout=25, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise GeoapifySearchError(f"Geoapify search failed with HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise GeoapifySearchError("Geoapify search could not reach the provider") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise GeoapifySearchError("Geoapify search returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise GeoapifySearchError("Geoapify search returned an invalid response object")
    return decoded


def _geocoding_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    rows = response.get("results")
    if rows is None:
        return _feature_rows(response)
    if not isinstance(rows, list):
        raise GeoapifySearchError("Geoapify geocoding response has invalid results")
    return [row for row in rows if isinstance(row, dict)]


def _feature_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    features = response.get("features", [])
    if not isinstance(features, list):
        raise GeoapifySearchError("Geoapify response has invalid features")
    rows: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if isinstance(properties, dict):
            rows.append(properties)
    return rows


def _detail_properties(response: dict[str, Any]) -> dict[str, Any]:
    for properties in _feature_rows(response):
        if _string(properties.get("feature_type")) == "details":
            return properties
    return {}


def _provider_query(query: str, target_market: str) -> str:
    role_words = (
        "manufacturer",
        "manufacturers",
        "distributor",
        "distributors",
        "wholesaler",
        "wholesalers",
        "buyer",
        "buyers",
        "importer",
        "importers",
        "agent",
        "agents",
        "company",
        "companies",
    )
    cleaned = re.sub(
        rf"\b(?:{'|'.join(role_words)})\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    cleaned = " ".join(cleaned.split())
    if cleaned:
        return cleaned
    return target_market or query


def _unique_place_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        place_id = _string(row.get("place_id"))
        key = place_id or "|".join(
            [_first_string(row, "name", "address_line1"), _first_string(row, "formatted")]
        )
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _normalize_result(properties: dict[str, Any]) -> SearchResult | None:
    title = _first_string(properties, "name", "address_line1")
    place_id = _string(properties.get("place_id"))
    if not title or not place_id:
        return None

    contact = properties.get("contact")
    contact_values = contact if isinstance(contact, dict) else {}
    website = _absolute_url(
        _first_string(properties, "website")
        or _first_string(contact_values, "website")
    )
    email = _first_string(contact_values, "email")
    phone = _first_string(contact_values, "phone")
    address = _first_string(properties, "formatted", "address_line2")
    categories = properties.get("categories", [])
    category_text = ", ".join(
        value.strip() for value in categories if isinstance(value, str) and value.strip()
    ) if isinstance(categories, list) else ""
    source_url = website or GEOAPIFY_MAP_URL
    return SearchResult(
        url=source_url,
        title=title,
        snippet=" | ".join(value for value in [address, phone, category_text] if value),
        canonical_key="" if website else f"geoapify-place:{place_id}",
        email=email,
        phone=phone,
        source_url=source_url,
    )


def _first_string(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _string(values.get(key))
        if value:
            return value
    return ""


def _absolute_url(value: str) -> str:
    if not value:
        return ""
    return value if "://" in value else f"https://{value.lstrip('/')}"


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
