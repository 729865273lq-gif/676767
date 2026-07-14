from __future__ import annotations

from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.platform.models import ConnectorCredential
from app.platform.service import AuditService, OrganizationService


class CredentialCipher:
    """Fernet encryption with support for a raw 32-byte key in isolated tests."""

    def __init__(self, key: str) -> None:
        encoded_key = urlsafe_b64encode(key.encode()) if len(key) == 32 else key.encode()
        self._fernet = Fernet(encoded_key)

    def encrypt(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()


class CredentialService:
    def __init__(self, session: Session, cipher: CredentialCipher) -> None:
        self.session = session
        self.cipher = cipher
        self.organizations = OrganizationService(session)
        self.audit = AuditService(session)

    def create(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        connector_type: str,
        key_label: str,
        secret: str,
    ) -> ConnectorCredential:
        self.organizations.require_admin(actor_user_id, organization_id)
        credential = ConnectorCredential(
            organization_id=organization_id,
            connector_type=connector_type,
            key_label=key_label,
            ciphertext=self.cipher.encrypt(secret),
            last_four=secret[-4:],
        )
        self.session.add(credential)
        self.session.flush()
        self.audit.record(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            event_type="connector_credential.created",
            metadata={
                "connector_type": connector_type,
                "credential_id": credential.id,
                "key_label": key_label,
            },
        )
        return credential

    def update_secret(
        self, *, actor_user_id: str, credential: ConnectorCredential, secret: str
    ) -> ConnectorCredential:
        self.organizations.require_admin(actor_user_id, credential.organization_id)
        credential.ciphertext = self.cipher.encrypt(secret)
        credential.last_four = secret[-4:]
        self.audit.record(
            actor_user_id=actor_user_id,
            organization_id=credential.organization_id,
            event_type="connector_credential.updated",
            metadata={
                "connector_type": credential.connector_type,
                "credential_id": credential.id,
                "key_label": credential.key_label,
            },
        )
        return credential
