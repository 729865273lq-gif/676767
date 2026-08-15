from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.contact_discovery.contracts import DiscoveredContact

HUNTER_DOMAIN_SEARCH_ENDPOINT = "https://api.hunter.io/v2/domain-search"

RequestSender = Callable[[str], dict[str, object]]


class HunterContactDiscoveryConfigurationError(ValueError):
    """Raised when Hunter contact discovery has not been configured."""


class HunterContactDiscoveryError(RuntimeError):
    """Raised when Hunter cannot return normalized contacts."""


class HunterContactDiscoveryConnector:
    connector_id = "hunter"

    def __init__(self, api_key: str | None, request_sender: RequestSender | None = None) -> None:
        if not api_key:
            raise HunterContactDiscoveryConfigurationError("HUNTER_API_KEY is not configured")
        self.api_key = api_key
        self._request_sender = request_sender or _get_json

    def discover(self, domain: str, limit: int) -> list[DiscoveredContact]:
        normalized_domain = domain.strip().lower().removeprefix("www.")
        if not normalized_domain:
            raise ValueError("domain is required")
        bounded_limit = max(1, min(limit, 25))
        query = urlencode(
            {
                "domain": normalized_domain,
                "api_key": self.api_key,
                "limit": bounded_limit,
            }
        )
        payload = self._request_sender(f"{HUNTER_DOMAIN_SEARCH_ENDPOINT}?{query}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise HunterContactDiscoveryError("Hunter response is missing data")
        emails = data.get("emails")
        if not isinstance(emails, list):
            raise HunterContactDiscoveryError("Hunter response is missing emails")

        contacts: list[DiscoveredContact] = []
        for item in emails:
            if not isinstance(item, dict):
                continue
            email = _string(item.get("value"))
            if not email:
                continue
            first_name = _string(item.get("first_name"))
            last_name = _string(item.get("last_name"))
            name = " ".join(part for part in [first_name, last_name] if part).strip()
            contacts.append(
                DiscoveredContact(
                    name=name or email.split("@")[0],
                    title=_string(item.get("position")),
                    email=email,
                    phone=_first_phone(item.get("phone_number")),
                    linkedin_url=_string(item.get("linkedin")),
                    confidence=_integer(item.get("confidence")),
                    verification_status=_verification_status(item.get("verification")),
                    source="Hunter",
                )
            )
        return contacts


def _get_json(url: str) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "trade-axis/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        raise HunterContactDiscoveryError(
            f"Hunter contact discovery failed with HTTP {error.code}"
        ) from error
    except URLError as error:
        raise HunterContactDiscoveryError("Hunter contact discovery could not reach the provider") from error

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise HunterContactDiscoveryError("Hunter contact discovery returned invalid JSON") from error
    if not isinstance(data, dict):
        raise HunterContactDiscoveryError("Hunter contact discovery returned an invalid response")
    return data


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _first_phone(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            phone = _string(item)
            if phone:
                return phone
    return ""


def _verification_status(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return _string(value.get("status"))
