from __future__ import annotations

import re
import socket

from app.connectors.email_verification.contracts import EmailVerificationResult

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})$", re.IGNORECASE)


class DomainEmailVerificationError(RuntimeError):
    """Raised when the free domain-level email check cannot be completed."""


class DomainEmailVerificationConnector:
    connector_id = "domain-email-check"

    def verify(self, email: str) -> EmailVerificationResult:
        normalized_email = email.strip().lower()
        match = EMAIL_PATTERN.fullmatch(normalized_email)
        if match is None:
            raise DomainEmailVerificationError("email format is invalid")
        domain = match.group(1)
        try:
            addresses = socket.getaddrinfo(domain, 443)
        except socket.gaierror:
            addresses = []
        return EmailVerificationResult(
            email=normalized_email,
            status="domain_reachable" if addresses else "domain_unreachable",
            sub_status="mailbox_not_verified",
            provider="Basic domain check",
            deliverable=False,
        )
