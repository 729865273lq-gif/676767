from __future__ import annotations

from typing import Protocol

from app.agents.base.contracts import LlmCompletion
from app.connectors.base import Connector
from app.connectors.llm.embedding import EmbeddingConnector
from app.connectors.llm.openai_compatible import (
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingConnector,
)


class LlmConnector(Connector, Protocol):
    async def complete(self, prompt: str) -> LlmCompletion: ...


__all__ = [
    "EmbeddingConfigurationError",
    "EmbeddingConnector",
    "EmbeddingProviderError",
    "LlmConnector",
    "OpenAICompatibleEmbeddingConnector",
]
