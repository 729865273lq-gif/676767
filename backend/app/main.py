from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.shared.config import Settings
from app.shared.db import build_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or Settings.from_environment()
    app.state.settings = settings
    if not hasattr(app.state, "session_factory"):
        app.state.session_factory = build_session_factory(settings.database_url)
    yield


def create_app(session_factory: sessionmaker | None = None, settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="AI Foreign Trade Sales Platform", lifespan=lifespan)
    if session_factory is not None:
        app.state.session_factory = session_factory
    if settings is not None:
        app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": "foreign-trade-api", "status": "ok"}

    from app.platform.router import router as platform_router
    from app.workflow.router import router as workflow_router

    app.include_router(platform_router)
    app.include_router(workflow_router)

    return app


app = create_app()
