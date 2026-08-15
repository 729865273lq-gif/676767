from __future__ import annotations

import re

import httpx

from app.shared.config import Settings


class EmbeddingConfigurationError(ValueError):
    """Raised when the OpenAI-compatible embedding provider is not configured."""


class EmbeddingProviderError(RuntimeError):
    """Raised when the embedding provider rejects a request or returns an invalid response."""


class ChatConfigurationError(ValueError):
    """Raised when the OpenAI-compatible chat provider is not configured."""


class ChatProviderError(RuntimeError):
    """Raised when the chat provider rejects a request or returns an invalid response."""


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


class OpenAICompatibleChatConnector:
    connector_id = "openai-compatible-chat"
    version = "v1"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(timeout=30.0)

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAICompatibleChatConnector":
        missing = [
            name
            for name, value in {
                "LLM_API_BASE": settings.llm_api_base,
                "LLM_API_KEY": settings.llm_api_key,
            }.items()
            if not value
        ]
        if missing:
            raise ChatConfigurationError(
                "chat provider is not configured: " + ", ".join(missing)
            )
        return cls(
            base_url=settings.llm_api_base or "",
            api_key=settings.llm_api_key or "",
            model=settings.llm_model,
        )

    def classify_intent(self, subject: str, body: str) -> str | None:
        """Ask the model to pick a reply intent; returns ``None`` on failure."""
        prompt = (
            "Classify this customer reply into exactly one of: interested, question, "
            "not_now, not_interested, out_of_office, other. Reply with only the word.\n"
            f"Subject: {subject}\nBody: {body}"
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "You classify sales reply intent."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers
            )
        except httpx.HTTPError as error:
            raise ChatProviderError("chat provider could not be reached") from error
        if response.status_code != 200:
            raise ChatProviderError(f"chat provider returned HTTP {response.status_code}")
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ChatProviderError("chat provider returned an invalid response") from error
        return _normalize_intent_token(str(content)) or None

    def close(self) -> None:
        """Release the shared httpx client."""
        self._client.close()


def _normalize_intent_token(content: str) -> str:
    # Lowercase, map spaces to underscores (so "not interested" -> "not_interested"), and
    # strip punctuation so "Interested." or "interested\n" match the enum.
    normalized = content.lower().replace(" ", "_")
    return re.sub(r"[^a-z_]", "", normalized)
