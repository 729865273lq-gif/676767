from __future__ import annotations

from typing import Protocol

from app.connectors.base import Connector


class StorageConnector(Connector, Protocol):
    async def put(self, key: str, content: bytes) -> None: ...
