from __future__ import annotations

from typing import Protocol

from app.agents.base.contracts import OutboundMessage
from app.connectors.base import Connector
from app.connectors.email.imap import (
    ImapConfigurationError,
    ImapConnector,
    ImapError,
    InboundEmailRecord,
)
from app.connectors.email.smtp import EmailDeliveryConfigurationError, EmailDeliveryError, SmtpEmailConnector


class EmailConnector(Connector, Protocol):
    def send(self, message: OutboundMessage, idempotency_key: str) -> str: ...


__all__ = [
    "EmailConnector",
    "EmailDeliveryConfigurationError",
    "EmailDeliveryError",
    "ImapConfigurationError",
    "ImapConnector",
    "ImapError",
    "InboundEmailRecord",
    "SmtpEmailConnector",
]
