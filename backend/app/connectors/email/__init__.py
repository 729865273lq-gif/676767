from __future__ import annotations

from typing import Protocol

from app.agents.base.contracts import OutboundMessage
from app.connectors.base import Connector


class EmailConnector(Connector, Protocol):
    async def send(self, message: OutboundMessage, idempotency_key: str) -> str: ...
