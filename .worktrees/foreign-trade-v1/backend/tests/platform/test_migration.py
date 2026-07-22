from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_platform_migration_creates_tenant_foundation_tables(tmp_path: Path) -> None:
    workspace_root = Path(__file__).resolve().parents[3]
    database_path = tmp_path / "platform.sqlite"
    config = Config(str(workspace_root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(workspace_root / "database" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(f"sqlite+pysqlite:///{database_path}")).get_table_names())
    assert {"organizations", "users", "user_memberships", "connector_credentials", "audit_events"} <= tables


def test_platform_migration_uses_database_url_environment(monkeypatch, tmp_path: Path) -> None:
    workspace_root = Path(__file__).resolve().parents[3]
    database_path = tmp_path / "environment.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path}")
    config = Config(str(workspace_root / "backend" / "alembic.ini"))

    command.upgrade(config, "head")

    assert "organizations" in inspect(create_engine(f"sqlite+pysqlite:///{database_path}")).get_table_names()
