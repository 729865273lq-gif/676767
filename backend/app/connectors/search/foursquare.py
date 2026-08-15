from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import truststore

from app.agents.base.contracts import SearchResult

FOURSQUARE_SEARCH_ENDPOINT = "https://places-api.foursquare.com/places/search"
FOURSQUARE_API_VERSION = "2025-06-17"
FOURSQUARE_PUBLIC_PLACE_URL = "https://foursquare.com/placemakers/review-place"

RequestSender = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]


class FoursquareSearchError(RuntimeError):
    """Raised when Foursquare cannot return normalized place results."""


class FoursquareSearchConnector:
    connector_id = "foursquare"
    version = "2025-06-17"

    def __init__(
        self,
        api_key: str,
        request_sender: RequestSender | None = None,
        *,
        target_market: str = "",
    ) -> None:
        if not api_key.strip():
            raise ValueError("Foursquare API key is required")
        self._api_key = api_key.strip()
        self._request_sender = request_sender or _get_json
        self._target_market = target_market.strip()

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        count = min(max(limit, 1), 50)
        parameters = {
            "query": _provider_query(query.strip(), self._target_market),
            "limit": str(count),
            "sort": "RELEVANCE",
            "tel_format": "E164",
        }
        if self._target_market:
            parameters["near"] = self._target_market
        response = await asyncio.to_thread(
            self._request_sender,
            FOURSQUARE_SEARCH_ENDPOINT,
            parameters,
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "X-Places-Api-Version": FOURSQUARE_API_VERSION,
                "User-Agent": "TradeAxis/1.0",
            },
        )
        return _normalize_results(response)[:count]


def _get_json(
    endpoint: str,
    parameters: dict[str, str],
    headers: dict[str, str],
) -> dict[str, Any]:
    request = Request(f"{endpoint}?{urlencode(parameters)}", headers=headers)
    try:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(request, timeout=25, context=context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise FoursquareSearchError(
            f"Foursquare place search failed with HTTP {error.code}"
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise FoursquareSearchError(
            "Foursquare place search could not reach the provider"
        ) from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise FoursquareSearchError("Foursquare place search returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise FoursquareSearchError(
            "Foursquare place search returned an invalid response object"
        )
    return decoded


def _provider_query(query: str, target_market: str) -> str:
    if not target_market:
        return query
    cleaned = query.replace(target_market, " ")
    return " ".join(cleaned.split()) or query


def _normalize_results(response: dict[str, Any]) -> list[SearchResult]:
    rows = response.get("results", [])
    if not isinstance(rows, list):
        raise FoursquareSearchError("Foursquare response has invalid results")

    results: list[SearchResult] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        place_id = _string(row.get("fsq_place_id"))
        title = _string(row.get("name"))
        if not place_id or not title or place_id in seen:
            continue
        seen.add(place_id)

        website = _absolute_url(_string(row.get("website")))
        source_url = _string(row.get("placemaker_url")) or (
            f"{FOURSQUARE_PUBLIC_PLACE_URL}/{place_id}"
        )
        location = row.get("location")
        address = (
            _string(location.get("formatted_address"))
            if isinstance(location, dict)
            else ""
        )
        categories = row.get("categories", [])
        category_text = ", ".join(
            _string(category.get("name"))
            for category in categories
            if isinstance(category, dict) and _string(category.get("name"))
        ) if isinstance(categories, list) else ""
        phone = _string(row.get("tel"))
        results.append(
            SearchResult(
                url=website or source_url,
                title=title,
                snippet=" | ".join(
                    value for value in [address, phone, category_text] if value
                ),
                canonical_key="" if website else f"foursquare-place:{place_id}",
                email=_string(row.get("email")),
                phone=phone,
                social_profiles=_social_profiles(row.get("social_media")),
                source_url=source_url,
            )
        )
    return results


def _social_profiles(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    profiles: list[dict[str, str]] = []
    facebook_id = _string(value.get("facebook_id"))
    instagram = _string(value.get("instagram")).lstrip("@")
    twitter = _string(value.get("twitter")).lstrip("@")
    if facebook_id:
        profiles.append(
            {"platform": "Facebook", "url": f"https://www.facebook.com/{facebook_id}"}
        )
    if instagram:
        profiles.append(
            {"platform": "Instagram", "url": f"https://www.instagram.com/{instagram}"}
        )
    if twitter:
        profiles.append({"platform": "X", "url": f"https://x.com/{twitter}"})
    return profiles


def _absolute_url(value: str) -> str:
    if not value:
        return ""
    return value if "://" in value else f"https://{value.lstrip('/')}"


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
