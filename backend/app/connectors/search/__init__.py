from __future__ import annotations

from typing import Protocol

from app.agents.base.contracts import SearchResult
from app.connectors.base import Connector


class SearchConnector(Connector, Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...
