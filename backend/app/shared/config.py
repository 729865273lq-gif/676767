from collections.abc import Mapping
from dataclasses import dataclass
from os import environ

from cryptography.fernet import Fernet, InvalidToken


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is unsafe or incomplete."""


PLACEHOLDER_PREFIXES = ("replace-with", "change-me", "your-", "example", "placeholder")


@dataclass(frozen=True)
class Settings:
    app_secret: str
    credential_encryption_key: str
    database_url: str
    redis_url: str
    s3_endpoint: str
    bocha_api_key: str | None = None
    google_cse_api_key: str | None = None
    google_cse_cx: str | None = None
    google_places_api_key: str | None = None
    tomtom_api_key: str | None = None
    geoapify_api_key: str | None = None
    foursquare_api_key: str | None = None
    serpapi_api_key: str | None = None
    dataforseo_login: str | None = None
    dataforseo_password: str | None = None
    tradesparq_api_id: str | None = None
    tradesparq_api_secret: str | None = None
    hunter_api_key: str | None = None
    apollo_api_key: str | None = None
    zerobounce_api_key: str | None = None
    neverbounce_api_key: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "Trade Axis"
    smtp_use_tls: bool = True
    imap_host: str | None = None
    imap_port: int = 993
    imap_sent_mailbox: str = ""

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "Settings":
        environment = environ if values is None else values
        app_secret = _required_secret(environment, "APP_SECRET")
        credential_encryption_key = _required_secret(environment, "CREDENTIAL_ENCRYPTION_KEY")

        try:
            Fernet(credential_encryption_key.encode())
        except (ValueError, InvalidToken) as error:
            raise ConfigurationError("CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from error

        return cls(
            app_secret=app_secret,
            credential_encryption_key=credential_encryption_key,
            database_url=environment.get(
                "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/foreign_trade"
            ),
            redis_url=environment.get("REDIS_URL", "redis://redis:6379/0"),
            s3_endpoint=environment.get("S3_ENDPOINT", "http://minio:9000"),
            bocha_api_key=_optional_secret(environment, "BOCHA_API_KEY"),
            google_cse_api_key=_optional_secret(environment, "GOOGLE_CSE_API_KEY"),
            google_cse_cx=_optional_secret(environment, "GOOGLE_CSE_CX"),
            google_places_api_key=_optional_secret(environment, "GOOGLE_PLACES_API_KEY"),
            tomtom_api_key=_optional_secret(environment, "TOMTOM_API_KEY"),
            geoapify_api_key=_optional_secret(environment, "GEOAPIFY_API_KEY"),
            foursquare_api_key=_optional_secret(environment, "FOURSQUARE_API_KEY"),
            serpapi_api_key=_optional_secret(environment, "SERPAPI_API_KEY"),
            dataforseo_login=_optional_secret(environment, "DATAFORSEO_LOGIN"),
            dataforseo_password=_optional_secret(environment, "DATAFORSEO_PASSWORD"),
            tradesparq_api_id=_optional_secret(environment, "TRADESPARQ_API_ID"),
            tradesparq_api_secret=_optional_secret(environment, "TRADESPARQ_API_SECRET"),
            hunter_api_key=_optional_secret(environment, "HUNTER_API_KEY"),
            apollo_api_key=_optional_secret(environment, "APOLLO_API_KEY"),
            zerobounce_api_key=_optional_secret(environment, "ZEROBOUNCE_API_KEY"),
            neverbounce_api_key=_optional_secret(environment, "NEVERBOUNCE_API_KEY"),
            smtp_host=_optional_secret(environment, "SMTP_HOST"),
            smtp_port=_optional_int(environment, "SMTP_PORT", 587),
            smtp_username=_optional_secret(environment, "SMTP_USERNAME"),
            smtp_password=_optional_secret(environment, "SMTP_PASSWORD"),
            smtp_from_email=_optional_secret(environment, "SMTP_FROM_EMAIL"),
            smtp_from_name=environment.get("SMTP_FROM_NAME", "Trade Axis").strip() or "Trade Axis",
            smtp_use_tls=_optional_bool(environment, "SMTP_USE_TLS", True),
            imap_host=_optional_secret(environment, "IMAP_HOST"),
            imap_port=_optional_int(environment, "IMAP_PORT", 993),
            imap_sent_mailbox=environment.get("IMAP_SENT_MAILBOX", "").strip(),
        )


def _required_secret(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
        raise ConfigurationError(f"{name} must be configured with a non-placeholder value")
    if name == "APP_SECRET" and len(value) < 32:
        raise ConfigurationError("APP_SECRET must contain at least 32 characters")
    return value


def _optional_secret(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name, "").strip()
    if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
        return None
    return value


def _optional_int(environment: Mapping[str, str], name: str, default: int) -> int:
    value = environment.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error


def _optional_bool(environment: Mapping[str, str], name: str, default: bool) -> bool:
    value = environment.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")
