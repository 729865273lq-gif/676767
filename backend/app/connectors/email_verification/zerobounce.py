from collections.abc import Callable
from json import JSONDecodeError
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.email_verification.contracts import EmailVerificationResult


class ZeroBounceEmailVerificationConfigurationError(ValueError):
    """Raised when ZeroBounce email verification has not been configured."""


class ZeroBounceEmailVerificationError(RuntimeError):
    """Raised when ZeroBounce cannot return a normalized verification result."""


class ZeroBounceEmailVerificationConnector:
    connector_id = "zerobounce-email-verification"
    base_url = "https://api.zerobounce.net/v2/validate"

    def __init__(self, api_key: str | None, request_sender: Callable[[Request], bytes] | None = None) -> None:
        if not api_key:
            raise ZeroBounceEmailVerificationConfigurationError("ZEROBOUNCE_API_KEY is not configured")
        self.api_key = api_key
        self.request_sender = request_sender or _send_request

    def verify(self, email: str) -> EmailVerificationResult:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ZeroBounceEmailVerificationError("contact email is required")
        query = urlencode({"api_key": self.api_key, "email": normalized_email})
        request = Request(f"{self.base_url}?{query}", headers={"Accept": "application/json"})
        try:
            payload = json.loads(self.request_sender(request).decode("utf-8"))
        except HTTPError as error:
            raise ZeroBounceEmailVerificationError(
                f"ZeroBounce email verification failed with HTTP {error.code}"
            ) from error
        except URLError as error:
            raise ZeroBounceEmailVerificationError("ZeroBounce email verification could not reach the provider") from error
        except JSONDecodeError as error:
            raise ZeroBounceEmailVerificationError("ZeroBounce email verification returned invalid JSON") from error

        if not isinstance(payload, dict):
            raise ZeroBounceEmailVerificationError("ZeroBounce email verification returned an invalid response")
        status = _string_value(payload.get("status"))
        if not status:
            raise ZeroBounceEmailVerificationError("ZeroBounce email verification response is missing status")
        return EmailVerificationResult(
            email=_string_value(payload.get("address")) or normalized_email,
            status=status,
            sub_status=_string_value(payload.get("sub_status")),
            provider="ZeroBounce",
            deliverable=status == "valid",
        )


def _send_request(request: Request) -> bytes:
    with urlopen(request, timeout=20) as response:
        return response.read()


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
