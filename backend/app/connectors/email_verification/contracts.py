from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailVerificationResult:
    email: str
    status: str
    sub_status: str = ""
    provider: str = ""
    deliverable: bool = False


class EmailVerificationConnector(Protocol):
    connector_id: str

    def verify(self, email: str) -> EmailVerificationResult:
        """Verify a mailbox with a provider and return a normalized result."""
