import importlib
import sys

from cryptography.fernet import Fernet
import pytest

from app.shared.config import ConfigurationError


def valid_environment() -> dict[str, str]:
    return {
        "APP_SECRET": "a-local-test-secret-that-is-long-enough",
        "CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "REDIS_URL": "redis://redis:6379/0",
    }


def load_worker(monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    sys.modules.pop("app.worker", None)
    return importlib.import_module("app.worker")


def test_worker_initialization_rejects_placeholder_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = valid_environment()
    environment["APP_SECRET"] = "replace-with-a-real-secret"

    with pytest.raises(ConfigurationError, match="APP_SECRET"):
        load_worker(monkeypatch, environment)


def test_worker_initialization_creates_celery_app_for_valid_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = load_worker(monkeypatch, valid_environment())

    assert worker.celery_app.conf.broker_url == "redis://redis:6379/0"
