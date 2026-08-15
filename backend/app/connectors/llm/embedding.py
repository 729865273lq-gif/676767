from __future__ import annotations

from typing import Protocol

from app.connectors.base import Connector


class EmbeddingConnector(Connector, Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
