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
                "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/foreign_trade"
            ),
            redis_url=environment.get("REDIS_URL", "redis://redis:6379/0"),
            s3_endpoint=environment.get("S3_ENDPOINT", "http://minio:9000"),
        )


def _required_secret(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value or value.lower().startswith(PLACEHOLDER_PREFIXES):
        raise ConfigurationError(f"{name} must be configured with a non-placeholder value")
    if name == "APP_SECRET" and len(value) < 32:
        raise ConfigurationError("APP_SECRET must contain at least 32 characters")
    return value
