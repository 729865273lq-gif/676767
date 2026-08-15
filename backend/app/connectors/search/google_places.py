from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agents.base.contracts import SearchResult

GOOGLE_PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.primaryType",
        "places.businessStatus",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)

RequestSender = Callable[[str, dict[str, Any], str, str], dict[str, Any]]


class GooglePlacesSearchError(RuntimeError):
    """Raised when Google Places cannot return normalized business results."""


class GooglePlacesSearchConnector:
    connector_id = "google_places"
    version = "v1"

    def __init__(self, api_key: str, request_sender: RequestSender | None = None) -> None:
        if not api_key.strip():
            raise ValueError("Google Places API key is required")
        self._api_key = api_key.strip()
        self._request_sender = request_sender or _post_json

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        count = min(max(limit, 1), 60)
        results: list[SearchResult] = []
        page_token = ""

        while len(results) < count:
            payload: dict[str, Any] = {
                "textQuery": query.strip(),
                "pageSize": min(20, count - len(results)),
                "includePureServiceAreaBusinesses": True,
                "languageCode": "en",
            }
            if page_token:
                payload["pageToken"] = page_token
            response = await asyncio.to_thread(
                self._request_sender,
                GOOGLE_PLACES_ENDPOINT,
                payload,
                self._api_key,
                GOOGLE_PLACES_FIELD_MASK,
            )
            page_results = _normalize_results(response)
            results.extend(page_results)
            next_page_token = response.get("nextPageToken", "")
            if not isinstance(next_page_token, str) or not next_page_token or not page_results:
                break
            page_token = next_page_token

        return results[:count]


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    api_key: str,
    field_mask: str,
) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise GooglePlacesSearchError(
            f"Google Places request failed with HTTP {error.code}"
        ) from error
    except URLError as error:
        raise GooglePlacesSearchError("Google Places could not reach the provider") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise GooglePlacesSearchError("Google Places returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise GooglePlacesSearchError("Google Places returned an invalid response object")
    return decoded


def _normalize_results(response: dict[str, Any]) -> list[SearchResult]:
    raw_places = response.get("places", [])
    if raw_places is None:
        raw_places = []
    if not isinstance(raw_places, list):
        raise GooglePlacesSearchError("Google Places response has invalid places")

    results: list[SearchResult] = []
    for place in raw_places:
        if not isinstance(place, dict):
            continue
        place_id = _string(place.get("id"))
        display_name = place.get("displayName", {})
        title = _string(display_name.get("text")) if isinstance(display_name, dict) else ""
        website = _string(place.get("websiteUri"))
        maps_url = _string(place.get("googleMapsUri"))
        result_url = website or maps_url
        if not title or not result_url:
            continue
        phone = _string(place.get("internationalPhoneNumber")) or _string(
            place.get("nationalPhoneNumber")
        )
        details = [
            _string(place.get("formattedAddress")),
            phone,
            _string(place.get("primaryType")),
            _string(place.get("businessStatus")),
        ]
        results.append(
            SearchResult(
                url=result_url,
                title=title,
                snippet=" | ".join(item for item in details if item),
                canonical_key="" if website else f"google-place:{place_id}",
                phone=phone,
                source_url=maps_url or result_url,
            )
        )
    return results


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
