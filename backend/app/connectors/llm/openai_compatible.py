from __future__ import annotations

import httpx

from app.shared.config import Settings


class EmbeddingConfigurationError(ValueError):
    """Raised when the OpenAI-compatible embedding provider is not configured."""


class EmbeddingProviderError(RuntimeError):
    """Raised when the embedding provider rejects a request or returns an invalid response."""


class OpenAICompatibleEmbeddingConnector:
    connector_id = "openai-compatible-embedding"
    version = "v1"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAICompatibleEmbeddingConnector":
        missing = [
            name
            for name, value in {
                "EMBEDDING_API_BASE": settings.embedding_api_base,
                "EMBEDDING_API_KEY": settings.embedding_api_key,
            }.items()
            if not value
        ]
        if missing:
            raise EmbeddingConfigurationError(
                "embedding provider is not configured: " + ", ".join(missing)
            )
        return cls(
            base_url=settings.embedding_api_base or "",
            api_key=settings.embedding_api_key or "",
            model=settings.embedding_model,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self._model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(f"{self._base_url}/embeddings", json=payload, headers=headers)
            except httpx.HTTPError as error:
                raise EmbeddingProviderError("embedding provider could not be reached") from error
        if response.status_code != 200:
            raise EmbeddingProviderError(f"embedding provider returned HTTP {response.status_code}")
        data = response.json()
        entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise EmbeddingProviderError("embedding provider returned an invalid response")
        vectors = [
            entry.get("embedding")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("embedding"), list)
        ]
        if len(vectors) != len(texts):
            raise EmbeddingProviderError("embedding provider returned an unexpected number of vectors")
        return vectors
