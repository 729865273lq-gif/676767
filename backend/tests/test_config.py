from cryptography.fernet import Fernet
import pytest

from app.shared.config import ConfigurationError, Settings


def valid_environment() -> dict[str, str]:
    return {
        "APP_SECRET": "a-local-test-secret-that-is-long-enough",
        "CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }


@pytest.mark.parametrize("name", ["APP_SECRET", "CREDENTIAL_ENCRYPTION_KEY"])
def test_settings_reject_placeholder_secrets(name: str) -> None:
    environment = valid_environment()
    environment[name] = "replace-with-a-real-secret"

    with pytest.raises(ConfigurationError, match=name):
        Settings.from_environment(environment)


def test_settings_rejects_invalid_fernet_key() -> None:
    environment = valid_environment()
    environment["CREDENTIAL_ENCRYPTION_KEY"] = "not-a-fernet-key"

    with pytest.raises(ConfigurationError, match="CREDENTIAL_ENCRYPTION_KEY"):
        Settings.from_environment(environment)


def test_settings_accepts_valid_runtime_configuration() -> None:
    environment = valid_environment()

    settings = Settings.from_environment(environment)

    assert settings.app_secret == environment["APP_SECRET"]
    assert settings.credential_encryption_key == environment["CREDENTIAL_ENCRYPTION_KEY"]


def test_settings_default_database_url_uses_declared_postgresql_driver() -> None:
    settings = Settings.from_environment(valid_environment())

    assert settings.database_url.startswith("postgresql+psycopg://")


def test_settings_reads_optional_bocha_api_key_without_making_it_required() -> None:
    values = valid_environment() | {"BOCHA_API_KEY": "bocha-local-key"}

    assert Settings.from_environment(values).bocha_api_key == "bocha-local-key"
    assert Settings.from_environment(valid_environment()).bocha_api_key is None


def test_settings_reads_optional_tomtom_api_key_without_making_it_required() -> None:
    values = valid_environment() | {"TOMTOM_API_KEY": "tomtom-local-key"}

    assert Settings.from_environment(values).tomtom_api_key == "tomtom-local-key"
    assert Settings.from_environment(valid_environment()).tomtom_api_key is None


def test_settings_reads_optional_geoapify_api_key_without_making_it_required() -> None:
    values = valid_environment() | {"GEOAPIFY_API_KEY": "geoapify-local-key"}

    assert Settings.from_environment(values).geoapify_api_key == "geoapify-local-key"
    assert Settings.from_environment(valid_environment()).geoapify_api_key is None


def test_settings_reads_optional_foursquare_api_key_without_making_it_required() -> None:
    values = valid_environment() | {"FOURSQUARE_API_KEY": "foursquare-local-key"}

    assert Settings.from_environment(values).foursquare_api_key == "foursquare-local-key"
    assert Settings.from_environment(valid_environment()).foursquare_api_key is None


def test_settings_reads_optional_tradesparq_credentials() -> None:
    values = valid_environment() | {
        "TRADESPARQ_API_ID": "tradesparq-local-id",
        "TRADESPARQ_API_SECRET": "tradesparq-local-secret",
    }

    settings = Settings.from_environment(values)

    assert settings.tradesparq_api_id == "tradesparq-local-id"
    assert settings.tradesparq_api_secret == "tradesparq-local-secret"
    assert Settings.from_environment(valid_environment()).tradesparq_api_id is None
    assert Settings.from_environment(valid_environment()).tradesparq_api_secret is None
