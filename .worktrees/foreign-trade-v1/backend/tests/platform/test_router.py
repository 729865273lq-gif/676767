import time

from cryptography.fernet import Fernet

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.platform.models import ConnectorCredential, MembershipRole, Organization, User, UserMembership
from app.shared.config import Settings
from app.shared.db import Base
from app.shared.security import PrincipalTokenCodec


APP_SECRET = "a-local-test-secret-that-is-long-enough"


def bearer_headers(user_id: str, expires_at: int | None = None) -> dict[str, str]:
    token = PrincipalTokenCodec(APP_SECRET).issue(
        user_id,
        expires_at=expires_at or int(time.time()) + 3_600,
    )
    return {"Authorization": f"Bearer {token}"}


def configured_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    acme = Organization(name="Acme Export")
    globex = Organization(name="Globex Import")
    member = User(email="member@acme.example", display_name="Acme Member")
    admin = User(email="admin@acme.example", display_name="Acme Admin")
    with factory.begin() as session:
        session.add_all([acme, globex, member, admin])
        session.flush()
        session.add_all(
            [
                UserMembership(
                    user_id=member.id,
                    organization_id=acme.id,
                    role=MembershipRole.MEMBER,
                ),
                UserMembership(
                    user_id=admin.id,
                    organization_id=acme.id,
                    role=MembershipRole.ADMIN,
                ),
            ]
        )
    settings = Settings(
        app_secret=APP_SECRET,
        credential_encryption_key=Fernet.generate_key().decode(),
        database_url="sqlite://",
        redis_url="redis://redis:6379/0",
        s3_endpoint="http://minio:9000",
    )
    client = TestClient(create_app(session_factory=factory, settings=settings))
    client.acme_id = acme.id  # type: ignore[attr-defined]
    client.globex_id = globex.id  # type: ignore[attr-defined]
    client.member_id = member.id  # type: ignore[attr-defined]
    client.admin_id = admin.id  # type: ignore[attr-defined]
    return client, factory


def test_membership_route_denies_cross_tenant_read() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.globex_id}/membership",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 403


def test_caller_controlled_user_header_cannot_impersonate_member() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers={"X-User-Id": client.member_id},  # type: ignore[attr-defined]
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_valid_signed_principal_can_read_own_membership() -> None:
    client, _ = configured_client()

    response = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    assert response.json()["role"] == "member"


def test_tampered_or_expired_principal_is_rejected() -> None:
    client, _ = configured_client()
    valid = bearer_headers(client.member_id)["Authorization"]
    expired = bearer_headers(client.member_id, expires_at=int(time.time()) - 1)

    tampered = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers={"Authorization": f"{valid}x"},
    )
    expired_response = client.get(
        f"/platform/organizations/{client.acme_id}/membership",  # type: ignore[attr-defined]
        headers=expired,
    )

    assert tampered.status_code == 401
    assert expired_response.status_code == 401


def test_credential_route_rejects_member_and_hides_admin_secret() -> None:
    client, factory = configured_client()
    payload = {"connector_type": "gmail", "key_label": "sales", "secret": "api-secret-value"}

    denied = client.post(
        f"/platform/organizations/{client.acme_id}/credentials",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json=payload,
    )
    approved = client.post(
        f"/platform/organizations/{client.acme_id}/credentials",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json=payload,
    )
    with factory() as session:
        credential = session.scalar(select(ConnectorCredential))

    assert denied.status_code == 403
    assert approved.status_code == 201
    assert "api-secret-value" not in approved.text
    assert credential is not None
    assert credential.ciphertext != "api-secret-value"


def test_lifespan_builds_runtime_session_factory_from_safe_settings(monkeypatch) -> None:
    monkeypatch.setenv("APP_SECRET", "a-local-test-secret-that-is-long-enough")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    with TestClient(create_app()) as client:
        assert client.app.state.settings.database_url == "sqlite+pysqlite:///:memory:"
        assert client.app.state.session_factory is not None
