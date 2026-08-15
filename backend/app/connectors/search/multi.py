from __future__ import annotations

import asyncio
import math
from typing import Protocol
from urllib.parse import urlparse

from app.agents.base.contracts import SearchResult


class SearchConnectorLike(Protocol):
    connector_id: str

    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


class MultiSearchError(RuntimeError):
    """Raised when all configured search providers fail."""


class MultiSearchConnector:
    connector_id = "multi_search"
    version = "v1"

    def __init__(self, connectors: list[SearchConnectorLike]) -> None:
        self._connectors = connectors

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not self._connectors:
            raise MultiSearchError("no search connectors are configured")
        count = min(max(limit, 1), 50)
        results: list[SearchResult] = []
        seen: set[str] = set()
        errors: list[str] = []
        provider_limit = min(50, max(5, math.ceil(count / len(self._connectors)) * 2))
        responses = await asyncio.gather(
            *(connector.search(query, provider_limit) for connector in self._connectors),
            return_exceptions=True,
        )
        provider_batches: list[list[SearchResult]] = []
        for connector, response in zip(self._connectors, responses, strict=True):
            if isinstance(response, BaseException):
                errors.append(f"{connector.connector_id}: {response}")
                continue
            provider_batches.append(response)

        max_batch_size = max((len(batch) for batch in provider_batches), default=0)
        for index in range(max_batch_size):
            for provider_results in provider_batches:
                if index >= len(provider_results):
                    continue
                result = provider_results[index]
                key = result.canonical_key.strip().lower() or _dedupe_key(result.url)
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
                if len(results) >= count:
                    return results

        if not results and errors:
            raise MultiSearchError("; ".join(errors))
        return results


def _dedupe_key(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"
