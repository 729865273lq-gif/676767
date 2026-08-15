from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.connectors.base import Connector


@dataclass(frozen=True)
class DiscoveredContact:
    name: str
    title: str
    email: str
    phone: str = ""
    linkedin_url: str = ""
    whatsapp: str = ""
    social_profiles: list[dict[str, str]] = field(default_factory=list)
    source_url: str = ""
    confidence: int | None = None
    verification_status: str = ""
    source: str = ""


class ContactDiscoveryConnector(Connector, Protocol):
    def discover(self, domain: str, limit: int) -> list[DiscoveredContact]: ...
