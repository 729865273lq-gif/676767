import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.platform.models import MembershipRole, Organization, ProductLine, User, UserMembership
from app.platform.search_keywords import (
    KeywordSource,
    ProductLineSearchKeywords,
    TranslationError,
    ensure_keywords_for_search,
    set_keywords_override,
    translate_keywords,
)
from app.shared.config import Settings
from app.shared.db import Base
from app.shared.security import PrincipalTokenCodec

APP_SECRET = "a-local-test-secret-that-is-long-enough"


class FakeChatConnector:
    def __init__(self, responses=None, default='{"keywords": ["translated keyword"]}'):
        self.responses = list(responses) if responses is not None else []
        self.default = default
        self.calls: list[str] = []

    def chat_text(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return self.default


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
    admin = User(email="admin@acme.example", display_name="Acme Admin")
    member = User(email="member@acme.example", display_name="Acme Member")
    with factory.begin() as session:
        session.add_all([acme, globex, admin, member])
        session.flush()
        session.add_all(
            [
                UserMembership(user_id=admin.id, organization_id=acme.id, role=MembershipRole.ADMIN),
                UserMembership(user_id=member.id, organization_id=acme.id, role=MembershipRole.MEMBER),
            ]
        )
    settings = Settings(
        app_secret=APP_SECRET,
        credential_encryption_key=Fernet.generate_key().decode(),
        database_url="sqlite://",
        redis_url="redis://redis:6379/0",
        s3_endpoint="http://minio:9000",
    )
    llm = FakeChatConnector()
    client = TestClient(create_app(session_factory=factory, settings=settings, llm_connector=llm))
    client.acme_id = acme.id  # type: ignore[attr-defined]
    client.globex_id = globex.id  # type: ignore[attr-defined]
    client.member_id = member.id  # type: ignore[attr-defined]
    client.admin_id = admin.id  # type: ignore[attr-defined]
    client.llm_connector = llm  # type: ignore[attr-defined]
    return client, factory


# --- Translation service ---


def test_translate_keywords_parses_structured_json() -> None:
    llm = FakeChatConnector(['{"keywords": ["LED Scheinwerfer", "Lagerbeleuchtung"]}'])
    result = translate_keywords(llm, "工业 LED 照明", ["LED 投光灯"], "de")
    assert result == ["LED Scheinwerfer", "Lagerbeleuchtung"]


def test_translate_keywords_strips_markdown_fences() -> None:
    llm = FakeChatConnector(['```json\n{"keywords": ["a", "b"]}\n```'])
    assert translate_keywords(llm, "name", ["k"], "de") == ["a", "b"]


def test_translate_keywords_retries_once_on_malformed_json() -> None:
    llm = FakeChatConnector(["not json", '{"keywords": ["retry ok"]}'])
    assert translate_keywords(llm, "name", ["k"], "de") == ["retry ok"]
    assert len(llm.calls) == 2


def test_translate_keywords_raises_clean_error_after_retry() -> None:
    llm = FakeChatConnector(["not json", "still not json"])
    with pytest.raises(TranslationError, match="关键词"):
        translate_keywords(llm, "name", ["k"], "de")


def test_translate_keywords_accepts_plain_list_json() -> None:
    llm = FakeChatConnector(['["a", "b", "c"]'])
    assert translate_keywords(llm, "name", ["k"], "de") == ["a", "b", "c"]


# --- ensure_keywords_for_search ---


def test_ensure_keywords_returns_none_when_llm_missing_and_no_row(session, organizations) -> None:
    product_line = ProductLine(organization_id=organizations["acme"].id, name="轴承", product_keywords=["轴承"])
    session.add(product_line)
    session.flush()

    assert ensure_keywords_for_search(session, None, product_line, "de") is None


def test_ensure_keywords_translates_and_persists_auto_row(session, organizations) -> None:
    product_line = ProductLine(organization_id=organizations["acme"].id, name="轴承", product_keywords=["轴承"])
    session.add(product_line)
    session.flush()
    llm = FakeChatConnector(['{"keywords": ["Lager", "Wälzlager"]}'])

    row = ensure_keywords_for_search(session, llm, product_line, "de")

    assert row.source == KeywordSource.AUTO
    assert row.keywords == ["Lager", "Wälzlager"]
    assert row.organization_id == organizations["acme"].id

    again = ensure_keywords_for_search(session, llm, product_line, "de")
    assert again.id == row.id
    assert len(llm.calls) == 1


# --- manual overrides ---


def test_manual_override_persists_and_is_never_auto_overwritten(session, organizations) -> None:
    product_line = ProductLine(organization_id=organizations["acme"].id, name="轴承", product_keywords=["轴承"])
    session.add(product_line)
    session.flush()

    manual = set_keywords_override(session, product_line, "de", ["Handlager", "Handlager"], "user-1")

    assert manual.source == KeywordSource.MANUAL
    assert manual.keywords == ["Handlager"]
    assert manual.updated_by_user_id == "user-1"

    llm = FakeChatConnector(['{"keywords": ["auto lager"]}'])
    row = ensure_keywords_for_search(session, llm, product_line, "de")

    assert row.source == KeywordSource.MANUAL
    assert row.keywords == ["Handlager"]
    assert len(llm.calls) == 0


# --- org isolation ---


def test_keywords_are_scoped_to_organization(session, organizations) -> None:
    acme_line = ProductLine(organization_id=organizations["acme"].id, name="Bearings")
    globex_line = ProductLine(organization_id=organizations["globex"].id, name="Bearings")
    session.add_all([acme_line, globex_line])
    session.flush()

    set_keywords_override(session, acme_line, "de", ["acme lager"], "u1")

    llm = FakeChatConnector(['{"keywords": ["globex lager"]}'])
    row = ensure_keywords_for_search(session, llm, globex_line, "de")

    assert row.keywords == ["globex lager"]
    assert row.organization_id == organizations["globex"].id

    acme_rows = session.scalars(
        select(ProductLineSearchKeywords).where(
            ProductLineSearchKeywords.product_line_id == acme_line.id
        )
    ).all()
    assert len(acme_rows) == 1
    assert acme_rows[0].keywords == ["acme lager"]


# --- router authz ---


def test_search_keyword_routes_enforce_roles_and_scope() -> None:
    client, _ = configured_client()
    created = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"name": "Bearings", "product_keywords": ["bearing"]},
    )
    product_line_id = created.json()["id"]

    denied_translate = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/search-keywords/translate",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"languages": ["de"]},
    )
    translated = client.post(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/search-keywords/translate",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"languages": ["de"]},
    )
    listed = client.get(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/search-keywords",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )
    denied_put = client.put(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/search-keywords/de",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
        json={"keywords": ["hand lager"]},
    )
    overridden = client.put(
        f"/platform/organizations/{client.acme_id}/product-lines/{product_line_id}/search-keywords/de",  # type: ignore[attr-defined]
        headers=bearer_headers(client.admin_id),  # type: ignore[attr-defined]
        json={"keywords": ["hand lager"]},
    )
    cross_tenant = client.get(
        f"/platform/organizations/{client.globex_id}/product-lines/{product_line_id}/search-keywords",  # type: ignore[attr-defined]
        headers=bearer_headers(client.member_id),  # type: ignore[attr-defined]
    )

    assert denied_translate.status_code == 403
    assert translated.status_code == 200
    assert translated.json()[0]["language"] == "de"
    assert translated.json()[0]["source"] == "auto"
    assert listed.status_code == 200
    assert listed.json()[0]["keywords"] == ["translated keyword"]
    assert denied_put.status_code == 403
    assert overridden.status_code == 200
    assert overridden.json()["source"] == "manual"
    assert overridden.json()["keywords"] == ["hand lager"]
    assert cross_tenant.status_code == 403


# --- migration chain ---


def test_migration_chain_creates_and_drops_search_keywords_table(tmp_path: Path) -> None:
    workspace_root = Path(__file__).resolve().parents[3]
    database_path = tmp_path / "chain.sqlite"
    config = Config(str(workspace_root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(workspace_root / "database" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    assert "product_line_search_keywords" in tables

    command.downgrade(config, "0026_inbox_lead")

    tables_after = set(inspect(create_engine(f"sqlite+pysqlite:///{database_path}")).get_table_names())
    assert "product_line_search_keywords" not in tables_after
