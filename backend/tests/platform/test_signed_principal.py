import pytest

from app.shared.security import InvalidPrincipalToken, PrincipalTokenCodec


def test_signed_principal_round_trips_user_and_expiry() -> None:
    codec = PrincipalTokenCodec("a-local-test-secret-that-is-long-enough")

    token = codec.issue("user-123", expires_at=2_000_000_000)
    principal = codec.verify(token, now=1_900_000_000)

    assert principal.user_id == "user-123"
    assert principal.expires_at == 2_000_000_000


@pytest.mark.parametrize("token", ["not-a-token", "eyJzdWIiOiJ1c2VyIn0.invalid-signature"])
def test_signed_principal_rejects_malformed_or_tampered_token(token: str) -> None:
    codec = PrincipalTokenCodec("a-local-test-secret-that-is-long-enough")

    with pytest.raises(InvalidPrincipalToken):
        codec.verify(token, now=1_900_000_000)


def test_signed_principal_rejects_expired_token() -> None:
    codec = PrincipalTokenCodec("a-local-test-secret-that-is-long-enough")
    token = codec.issue("user-123", expires_at=1_900_000_000)

    with pytest.raises(InvalidPrincipalToken):
        codec.verify(token, now=1_900_000_000)
