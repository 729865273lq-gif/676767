from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app.connectors.contact_discovery import ContactDiscoveryConnector
from app.connectors.email import EmailConnector
from app.connectors.email_verification import EmailVerificationConnector
from app.connectors.search import SearchConnector
from app.shared.config import Settings
from app.shared.db import build_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or Settings.from_environment()
    app.state.settings = settings
    if not hasattr(app.state, "session_factory"):
        app.state.session_factory = build_session_factory(settings.database_url)
    yield


def create_app(
    session_factory: sessionmaker | None = None,
    settings: Settings | None = None,
    email_connector: EmailConnector | None = None,
    contact_discovery_connector: ContactDiscoveryConnector | None = None,
    email_verification_connector: EmailVerificationConnector | None = None,
    search_connector: SearchConnector | None = None,
) -> FastAPI:
    app = FastAPI(title="AI Foreign Trade Sales Platform", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if session_factory is not None:
        app.state.session_factory = session_factory
    if settings is not None:
        app.state.settings = settings
    if email_connector is not None:
        app.state.email_connector = email_connector
    if contact_discovery_connector is not None:
        app.state.contact_discovery_connector = contact_discovery_connector
    if email_verification_connector is not None:
        app.state.email_verification_connector = email_verification_connector
    if search_connector is not None:
        app.state.search_connector = search_connector

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": "foreign-trade-api", "status": "ok"}

    from app.platform.router import router as platform_router
    from app.agents.customer.router import router as discovery_router
    from app.workflow.router import router as workflow_router

    app.include_router(platform_router)
    app.include_router(discovery_router)
    app.include_router(workflow_router)

    return app


app = create_app()
