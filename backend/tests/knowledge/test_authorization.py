from __future__ import annotations

import io
import time

from cryptography.fernet import Fernet
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.knowledge.vector_store import EMBEDDING_DIM, InMemoryVectorStore
from app.main import create_app
from app.platform.models import MembershipRole, Organization, ProductLine, User, UserMembership
from app.shared.config import Settings
from app.shared.db import Base
from app.shared.security import PrincipalTokenCodec

APP_SECRET = "a-local-test-secret-that-is-long-enough"

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class FakeEmbeddingConnector:
    connector_id = "fake-embedding"
    version = "v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] * EMBEDDING_DIM for _ in texts]


class FakeStorageConnector:
    connector_id = "fake-storage"
    version = "v1"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self.objects[key] = content

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def bearer_headers(user_id: str) -> dict[str, str]:
    token = PrincipalTokenCodec(APP_SECRET).issue(user_id, expires_at=int(time.time()) + 3_600)
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
    embedding_connector = FakeEmbeddingConnector()
    storage_connector = FakeStorageConnector()
    vector_store = InMemoryVectorStore()
    client = TestClient(
        create_app(
            session_factory=factory,
            settings=settings,
            embedding_connector=embedding_connector,
            storage_connector=storage_connector,
            vector_store=vector_store,
        )
    )
    client.storage_connector = storage_connector  # type: ignore[attr-defined]
    client.acme_id = acme.id  # type: ignore[attr-defined]
    client.globex_id = globex.id  # type: ignore[attr-defined]
    client.member_id = member.id  # type: ignore[attr-defined]
    client.admin_id = admin.id  # type: ignore[attr-defined]
    return client, factory


def upload_document(client: TestClient, organization_id: str, user_id: str):
    return client.post(
        f"/knowledge/organizations/{organization_id}/documents",
        headers=bearer_headers(user_id),
        files=[("file", ("spec.docx", docx_bytes("alpha beta gamma"), DOCX_CONTENT_TYPE))],
    )


def test_admin_can_upload_document() -> None:
    client, _ = configured_client()

    response = upload_document(client, client.acme_id, client.admin_id)  # type: ignore[attr-defined]

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["filename"] == "spec.docx"
    assert body["failure_message"] == ""
    assert client.storage_connector.objects  # type: ignore[attr-defined]


def test_member_cannot_upload_document() -> None:
    client, _ = configured_client()

    response = upload_document(client, client.acme_id, client.member_id)  # type: ignore[attr-defined]

    assert response.status_code == 403


def test_member_can_list_and_search_documents() -> None:
    client, _ = configured_client()
    upload = upload_document(client, client.acme_id, client.admin_id)  # type: ignore[attr-defined]
    assert upload.status_code == 201

    listed = client.get(
        f"/knowledge/organizations/{client.acme_id}/documents",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    searched = client.get(
        f"/knowledge/organizations/{client.acme_id}/search?query=alpha",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert listed.status_code == 200
    documents = listed.json()
    assert len(documents) == 1
    assert documents[0]["status"] == "ready"
    assert documents[0]["filename"] == "spec.docx"
    assert "failure_message" not in documents[0]
    assert searched.status_code == 200
    results = searched.json()
    assert results
    assert results[0]["document_filename"] == "spec.docx"
    assert results[0]["document_id"] == upload.json()["id"]


def test_cross_org_knowledge_access_is_rejected() -> None:
    client, _ = configured_client()

    listed = client.get(
        f"/knowledge/organizations/{client.globex_id}/documents",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    searched = client.get(
        f"/knowledge/organizations/{client.globex_id}/search?query=alpha",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    uploaded = upload_document(client, client.globex_id, client.member_id)  # type: ignore[attr-defined]

    assert listed.status_code == 403
    assert searched.status_code == 403
    assert uploaded.status_code == 403


def test_search_rejects_foreign_product_line_id() -> None:
    client, factory = configured_client()
    upload = upload_document(client, client.acme_id, client.admin_id)  # type: ignore[attr-defined]
    assert upload.status_code == 201

    with factory.begin() as session:
        foreign = ProductLine(organization_id=client.globex_id, name="Globex Line")  # type: ignore[attr-defined]
        session.add(foreign)
        session.flush()
        foreign_id = foreign.id

    response = client.get(
        f"/knowledge/organizations/{client.acme_id}/search?query=alpha&product_line_id={foreign_id}",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert response.status_code == 404
