from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.shared.config import Settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    Settings.from_environment()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AI Foreign Trade Sales Platform", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": "foreign-trade-api", "status": "ok"}

    return app


app = create_app()
