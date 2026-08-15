from __future__ import annotations

from typing import Protocol

from app.connectors.base import Connector
from app.connectors.storage.s3 import S3StorageConnector, StorageError


class StorageConnector(Connector, Protocol):
    async def put(self, key: str, content: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...


__all__ = ["S3StorageConnector", "StorageConnector", "StorageError"]
