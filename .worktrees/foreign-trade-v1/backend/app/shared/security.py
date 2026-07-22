from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import time


class InvalidPrincipalToken(ValueError):
    """Raised when an authentication token cannot establish a principal."""


@dataclass(frozen=True)
class SignedPrincipal:
    user_id: str
    expires_at: int


class PrincipalTokenCodec:
    """Small, dependency-free HMAC bearer token codec for the platform API."""

    def __init__(self, app_secret: str) -> None:
        self._secret = app_secret.encode()

    def issue(self, user_id: str, *, expires_at: int) -> str:
        if not user_id or not isinstance(expires_at, int) or isinstance(expires_at, bool):
            raise ValueError("user_id and integer expires_at are required")
        payload = json.dumps(
            {"exp": expires_at, "sub": user_id}, separators=(",", ":"), sort_keys=True
        ).encode()
        signature = hmac.digest(self._secret, payload, sha256)
        return f"{_encode(payload)}.{_encode(signature)}"

    def verify(self, token: str, *, now: int | None = None) -> SignedPrincipal:
        try:
            encoded_payload, encoded_signature = token.split(".")
            payload = _decode(encoded_payload)
            signature = _decode(encoded_signature)
        except (ValueError, UnicodeEncodeError) as error:
            raise InvalidPrincipalToken("invalid principal token") from error

        expected_signature = hmac.digest(self._secret, payload, sha256)
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidPrincipalToken("invalid principal token")

        try:
            claims = json.loads(payload)
            user_id = claims["sub"]
            expires_at = claims["exp"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidPrincipalToken("invalid principal token") from error

        if (
            not isinstance(user_id, str)
            or not user_id
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or expires_at <= (now if now is not None else int(time.time()))
        ):
            raise InvalidPrincipalToken("invalid principal token")
        return SignedPrincipal(user_id=user_id, expires_at=expires_at)


def _encode(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))
