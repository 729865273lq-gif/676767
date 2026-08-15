from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.agents.base.contracts import SearchResult

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

RequestSender = Callable[[str, dict[str, str | int]], dict[str, Any]]


class GoogleProgrammableSearchError(RuntimeError):
    """Raised when Google Programmable Search cannot return normalized results."""


class GoogleProgrammableSearchConnector:
    connector_id = "google_cse"
    version = "v1"

    def __init__(
        self,
        api_key: str,
        cx: str,
        request_sender: RequestSender | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Google CSE API key is required")
        if not cx.strip():
            raise ValueError("Google CSE search engine ID is required")
        self._api_key = api_key.strip()
        self._cx = cx.strip()
        self._request_sender = request_sender or _get_json

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        count = min(max(limit, 1), 50)
        results: list[SearchResult] = []
        start = 1
        while len(results) < count and start <= 91:
            page_size = min(10, count - len(results), 101 - start)
            response = await asyncio.to_thread(
                self._request_sender,
                GOOGLE_CSE_ENDPOINT,
                {
                    "key": self._api_key,
                    "cx": self._cx,
                    "q": query.strip(),
                    "num": page_size,
                    "start": start,
                },
            )
            page_results = _normalize_results(response)
            results.extend(page_results)
            if len(page_results) < page_size:
                break
            start += page_size
        return results[:count]


def _get_json(endpoint: str, params: dict[str, str | int]) -> dict[str, Any]:
    request = Request(
        f"{endpoint}?{urlencode(params)}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise GoogleProgrammableSearchError(
            f"Google Programmable Search request failed with HTTP {error.code}"
        ) from error
    except URLError as error:
        raise GoogleProgrammableSearchError(
            "Google Programmable Search request could not reach the provider"
        ) from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise GoogleProgrammableSearchError("Google Programmable Search returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise GoogleProgrammableSearchError(
            "Google Programmable Search returned an invalid response object"
        )
    return decoded


def _normalize_results(response: dict[str, Any]) -> list[SearchResult]:
    raw_results = response.get("items", [])
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise GoogleProgrammableSearchError("Google Programmable Search response has invalid items")

    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = item.get("link")
        title = item.get("title")
        if not isinstance(url, str) or not url or not isinstance(title, str) or not title:
            continue
        snippet = item.get("snippet") or ""
        results.append(SearchResult(url=url, title=title, snippet=str(snippet)))
    return results
