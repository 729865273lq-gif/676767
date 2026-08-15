import os
import pathlib

import uvicorn


def load_local_environment() -> None:
    repo = pathlib.Path(__file__).resolve().parent.parent
    env_file = repo / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:postgres@localhost:5432/foreign_trade"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["S3_ENDPOINT"] = "http://localhost:9000"


if __name__ == "__main__":
    load_local_environment()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")
