from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agents.base.contracts import SearchResult

BOCHA_WEB_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/web-search"

RequestSender = Callable[[str, bytes, str], dict[str, Any]]


class BochaSearchError(RuntimeError):
    """Raised when Bocha cannot return a normalized web-search response."""


class BochaSearchConnector:
    connector_id = "bocha"
    version = "v1"

    def __init__(self, api_key: str, request_sender: RequestSender | None = None) -> None:
        if not api_key.strip():
            raise ValueError("Bocha API key is required")
        self._api_key = api_key.strip()
        self._request_sender = request_sender or _post_json

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        count = min(max(limit, 1), 50)
        payload = json.dumps({"query": query.strip(), "count": count, "summary": True}).encode()
        response = await asyncio.to_thread(
            self._request_sender,
            BOCHA_WEB_SEARCH_ENDPOINT,
            payload,
            self._api_key,
        )
        return _normalize_results(response)[:count]


def _post_json(endpoint: str, payload: bytes, api_key: str) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise BochaSearchError(f"Bocha search request failed with HTTP {error.code}") from error
    except URLError as error:
        raise BochaSearchError("Bocha search request could not reach the provider") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise BochaSearchError("Bocha search returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise BochaSearchError("Bocha search returned an invalid response object")
    return decoded


def _normalize_results(response: dict[str, Any]) -> list[SearchResult]:
    data = response.get("data")
    if not isinstance(data, dict):
        raise BochaSearchError("Bocha search response is missing data")
    web_pages = data.get("webPages")
    if not isinstance(web_pages, dict):
        raise BochaSearchError("Bocha search response is missing web pages")
    raw_results = web_pages.get("value")
    if not isinstance(raw_results, list):
        raise BochaSearchError("Bocha search response is missing result values")

    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("name")
        if not isinstance(url, str) or not url or not isinstance(title, str) or not title:
            continue
        snippet = item.get("summary") or item.get("snippet") or ""
        results.append(SearchResult(url=url, title=title, snippet=str(snippet)))
    return results
