from cryptography.fernet import Fernet
from sqlalchemy import select

from app.platform.credentials import CredentialCipher, CredentialService
from app.platform.models import AuditEvent, ConnectorCredential


def test_cipher_round_trips_secret_without_storing_plaintext() -> None:
    cipher = CredentialCipher("a" * 32)

    encrypted = cipher.encrypt("sk-test-secret")

    assert encrypted != "sk-test-secret"
    assert cipher.decrypt(encrypted) == "sk-test-secret"


def test_credential_service_encrypts_secret_and_audits_only_safe_metadata(
    session, organizations, members
) -> None:
    secret = "workspace-secret-value"
    service = CredentialService(session, CredentialCipher(Fernet.generate_key().decode()))

    credential = service.create(
        actor_user_id=members["acme_admin"].user_id,
        organization_id=organizations["acme"].id,
        connector_type="gmail",
        key_label="outbound-mailbox",
        secret=secret,
    )
    session.flush()

    stored = session.scalar(select(ConnectorCredential).where(ConnectorCredential.id == credential.id))
    audit_event = session.scalar(select(AuditEvent).where(AuditEvent.organization_id == credential.organization_id))

    assert stored is not None
    assert stored.ciphertext != secret
    assert stored.last_four == "alue"
    assert secret not in str(stored.ciphertext)
    assert audit_event is not None
    assert secret not in str(audit_event.metadata_json)
    assert audit_event.metadata_json == {
        "connector_type": "gmail",
        "credential_id": credential.id,
        "key_label": "outbound-mailbox",
    }


def test_credential_update_rotates_ciphertext_without_auditing_the_secret(
    session, organizations, members
) -> None:
    service = CredentialService(session, CredentialCipher(Fernet.generate_key().decode()))
    credential = service.create(
        actor_user_id=members["acme_admin"].user_id,
        organization_id=organizations["acme"].id,
        connector_type="gmail",
        key_label="outbound-mailbox",
        secret="old-secret",
    )

    updated = service.update_secret(
        actor_user_id=members["acme_admin"].user_id,
        credential=credential,
        secret="rotated-secret",
    )
    session.flush()
    events = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all()

    assert updated.last_four == "cret"
    assert service.cipher.decrypt(updated.ciphertext) == "rotated-secret"
    assert events[-1].event_type == "connector_credential.updated"
    assert "rotated-secret" not in str(events[-1].metadata_json)
