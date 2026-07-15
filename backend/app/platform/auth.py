from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import scrypt
from secrets import token_bytes

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.models import MembershipRole, Organization, User, UserMembership


def hash_password(password: str) -> str:
    salt = token_bytes(16)
    digest = scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        _, salt, expected = encoded.split("$")
        return scrypt(password.encode(), salt=_decode(salt), n=2**14, r=8, p=1) == _decode(expected)
    except ValueError:
        return False


class AuthService:
    def __init__(self, session: Session): self.session = session

    def register(self, organization_name: str, display_name: str, email: str, password: str) -> tuple[User, Organization]:
        normalized = email.strip().lower()
        if self.session.scalar(select(User).where(User.email == normalized)):
            raise ValueError("email already registered")
        organization = Organization(name=organization_name.strip())
        user = User(email=normalized, display_name=display_name.strip(), password_hash=hash_password(password))
        self.session.add_all([organization, user])
        self.session.flush()
        self.session.add(UserMembership(user_id=user.id, organization_id=organization.id, role=MembershipRole.ADMIN))
        self.session.flush()
        return user, organization

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.session.scalar(select(User).where(User.email == email.strip().lower()))
        return user if user and verify_password(password, user.password_hash) else None


def _encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode()


def _decode(value: str) -> bytes:
    return urlsafe_b64decode(value.encode())
