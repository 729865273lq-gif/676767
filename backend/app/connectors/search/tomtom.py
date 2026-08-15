from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import truststore

from app.agents.base.contracts import SearchResult

TOMTOM_POI_SEARCH_ENDPOINT = "https://api.tomtom.com/search/2/poiSearch"
TOMTOM_PUBLIC_MAP_URL = "https://www.tomtom.com/maps"

RequestSender = Callable[[str, dict[str, str]], dict[str, Any]]


class TomTomSearchError(RuntimeError):
    """Raised when TomTom cannot return normalized POI results."""


class TomTomSearchConnector:
    connector_id = "tomtom"
    version = "v2"

    def __init__(self, api_key: str, request_sender: RequestSender | None = None) -> None:
        if not api_key.strip():
            raise ValueError("TomTom API key is required")
        self._api_key = api_key.strip()
        self._request_sender = request_sender or _get_json

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        count = min(max(limit, 1), 50)
        endpoint = f"{TOMTOM_POI_SEARCH_ENDPOINT}/{quote(query.strip(), safe='')}.json"
        response = await asyncio.to_thread(
            self._request_sender,
            endpoint,
            {
                "key": self._api_key,
                "limit": str(count),
                "typeahead": "false",
                "language": "en-US",
            },
        )
        return _normalize_results(response)[:count]


def _get_json(endpoint: str, parameters: dict[str, str]) -> dict[str, Any]:
    request = Request(
        f"{endpoint}?{urlencode(parameters)}",
        headers={"Accept": "application/json", "User-Agent": "TradeAxis/1.0"},
    )
    try:
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(request, timeout=20, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise TomTomSearchError(f"TomTom POI search failed with HTTP {error.code}") from error
    except URLError as error:
        raise TomTomSearchError("TomTom POI search could not reach the provider") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise TomTomSearchError("TomTom POI search returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise TomTomSearchError("TomTom POI search returned an invalid response object")
    return decoded


def _normalize_results(response: dict[str, Any]) -> list[SearchResult]:
    raw_results = response.get("results", [])
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise TomTomSearchError("TomTom POI search response has invalid results")

    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        poi = item.get("poi")
        if not isinstance(poi, dict):
            continue
        title = _string(poi.get("name"))
        place_id = _string(item.get("id"))
        if not title or not place_id:
            continue

        website = _absolute_url(_string(poi.get("url")))
        phone = _string(poi.get("phone"))
        address = item.get("address")
        formatted_address = (
            _string(address.get("freeformAddress")) if isinstance(address, dict) else ""
        )
        categories = poi.get("categories", [])
        category_text = ", ".join(
            value.strip() for value in categories if isinstance(value, str) and value.strip()
        )
        source_url = website or TOMTOM_PUBLIC_MAP_URL
        results.append(
            SearchResult(
                url=source_url,
                title=title,
                snippet=" | ".join(
                    value for value in [formatted_address, phone, category_text] if value
                ),
                canonical_key="" if website else f"tomtom-place:{place_id}",
                phone=phone,
                source_url=source_url,
            )
        )
    return results


def _absolute_url(value: str) -> str:
    if not value:
        return ""
    return value if "://" in value else f"https://{value.lstrip('/')}"


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
