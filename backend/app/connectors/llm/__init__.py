from __future__ import annotations

from typing import Protocol

from app.agents.base.contracts import LlmCompletion
from app.connectors.base import Connector


class LlmConnector(Connector, Protocol):
    async def complete(self, prompt: str) -> LlmCompletion: ...
