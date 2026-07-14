from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Settings:
    database_url: str = getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/foreign_trade")
    redis_url: str = getenv("REDIS_URL", "redis://localhost:6379/0")
    s3_endpoint: str = getenv("S3_ENDPOINT", "http://localhost:9000")
