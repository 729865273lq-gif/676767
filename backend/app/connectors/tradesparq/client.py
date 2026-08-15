from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import truststore

JsonObject = dict[str, Any]
RequestSender = Callable[[Request], JsonObject]


class TradesparqError(RuntimeError):
    """Raised when the Tradesparq API cannot return a valid response."""


class TradesparqClient:
    def __init__(
        self,
        api_id: str,
        api_secret: str,
        request_sender: RequestSender | None = None,
    ) -> None:
        if not api_id.strip() or not api_secret.strip():
            raise ValueError("Tradesparq API ID and secret are required")
        self._api_id = api_id.strip()
        self._api_secret = api_secret.strip()
        self._request_sender = request_sender or _send_json

    async def get(self, endpoint: str, parameters: Mapping[str, object] | None = None) -> JsonObject:
        url = _url_with_parameters(endpoint, parameters or {})
        request = Request(url, headers=self._headers(build_get_signature(self._api_secret, url)))
        return await asyncio.to_thread(self._request_sender, request)

    async def post(self, endpoint: str, payload: Mapping[str, object]) -> JsonObject:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = self._headers(build_post_signature(self._api_secret, payload))
        headers["Content-Type"] = "application/json; charset=UTF-8"
        request = Request(endpoint, data=body, headers=headers, method="POST")
        return await asyncio.to_thread(self._request_sender, request)

    def _headers(self, signature: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "TradeAxis/1.0",
            "X-API-UID": self._api_id,
            "X-API-REQUEST-SIGN": signature,
        }


def build_get_signature(api_secret: str, full_url: str) -> str:
    return hashlib.md5(f"{api_secret}{full_url}".encode()).hexdigest()  # noqa: S324


def build_post_signature(api_secret: str, payload: Mapping[str, object]) -> str:
    sorted_values = "".join(
        json.dumps(payload[key], ensure_ascii=False, separators=(",", ":"))
        for key in sorted(payload)
    )
    return hashlib.md5(f"{api_secret}{sorted_values}".encode()).hexdigest()  # noqa: S324


def _url_with_parameters(endpoint: str, parameters: Mapping[str, object]) -> str:
    if not parameters:
        return endpoint
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(parameters)}"


def _send_json(request: Request) -> JsonObject:
    try:
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(request, timeout=20, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise TradesparqError(f"Tradesparq request failed with HTTP {error.code}") from error
    except URLError as error:
        raise TradesparqError("Tradesparq API could not be reached") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise TradesparqError("Tradesparq returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise TradesparqError("Tradesparq returned an invalid response object")
    return decoded
