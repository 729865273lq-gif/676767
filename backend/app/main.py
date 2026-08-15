import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.connectors.contact_discovery import ContactDiscoveryConnector
from app.connectors.email import EmailConnector, ImapConfigurationError, ImapConnector
from app.connectors.email_verification import EmailVerificationConnector
from app.connectors.llm import (
    ChatConfigurationError,
    EmbeddingConfigurationError,
    EmbeddingConnector,
    OpenAICompatibleChatConnector,
    OpenAICompatibleEmbeddingConnector,
)
from app.connectors.search import SearchConnector
from app.connectors.storage import S3StorageConnector, StorageConnector
from app.crm.inbox import InboxService
from app.crm.models import MailboxCursor
from app.shared.config import Settings
from app.shared.db import build_session_factory

logger = logging.getLogger(__name__)


def _sync_inbox_for_organization(
    session_factory: sessionmaker,
    organization_id: str,
    imap_connector: ImapConnector,
    llm_connector: object | None,
) -> None:
    session = session_factory()
    try:
        InboxService(session, imap_connector, llm_connector).sync_organization_mailbox(organization_id)
    finally:
        session.close()


async def _inbox_poll_loop(app: FastAPI, settings: Settings) -> None:
    # A lightweight lifespan-based poll loop keeps mailboxes fresh without a local Celery
    # worker. This can later be replaced by a Celery beat schedule or a dedicated worker.
    logger.info("IMAP inbox poll loop started (every %s seconds)", settings.inbox_poll_seconds)
    while True:
        await asyncio.sleep(settings.inbox_poll_seconds)
        try:
            session = app.state.session_factory()
            try:
                organization_ids = list(
                    session.scalars(select(MailboxCursor.organization_id).distinct()).all()
                )
            finally:
                session.close()
            for organization_id in organization_ids:
                try:
                    await asyncio.to_thread(
                        _sync_inbox_for_organization,
                        app.state.session_factory,
                        organization_id,
                        app.state.imap_connector,
                        app.state.llm_connector,
                    )
                except Exception:
                    logger.exception("inbox poll failed for organization %s", organization_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("inbox poll iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or Settings.from_environment()
    app.state.settings = settings
    if not hasattr(app.state, "session_factory"):
        app.state.session_factory = build_session_factory(settings.database_url)
    if not hasattr(app.state, "storage_connector"):
        app.state.storage_connector = S3StorageConnector.from_settings(settings)
    if not hasattr(app.state, "embedding_connector"):
        try:
            app.state.embedding_connector = OpenAICompatibleEmbeddingConnector.from_settings(settings)
        except EmbeddingConfigurationError:
            app.state.embedding_connector = None
    if not hasattr(app.state, "imap_connector"):
        try:
            app.state.imap_connector = ImapConnector.from_settings(settings)
        except ImapConfigurationError:
            app.state.imap_connector = None
    if not hasattr(app.state, "llm_connector"):
        try:
            app.state.llm_connector = OpenAICompatibleChatConnector.from_settings(settings)
        except ChatConfigurationError:
            app.state.llm_connector = None

    poll_task: asyncio.Task | None = None
    if app.state.imap_connector is not None:
        poll_task = asyncio.create_task(_inbox_poll_loop(app, settings))
    try:
        yield
    finally:
        if poll_task is not None:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass


def create_app(
    session_factory: sessionmaker | None = None,
    settings: Settings | None = None,
    email_connector: EmailConnector | None = None,
    contact_discovery_connector: ContactDiscoveryConnector | None = None,
    email_verification_connector: EmailVerificationConnector | None = None,
    search_connector: SearchConnector | None = None,
    embedding_connector: EmbeddingConnector | None = None,
    storage_connector: StorageConnector | None = None,
    vector_store: object | None = None,
    imap_connector: ImapConnector | None = None,
    llm_connector: object | None = None,
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
    if embedding_connector is not None:
        app.state.embedding_connector = embedding_connector
    if storage_connector is not None:
        app.state.storage_connector = storage_connector
    if vector_store is not None:
        app.state.vector_store = vector_store
    if imap_connector is not None:
        app.state.imap_connector = imap_connector
    if llm_connector is not None:
        app.state.llm_connector = llm_connector

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": "foreign-trade-api", "status": "ok"}

    from app.platform.router import router as platform_router
    from app.agents.customer.router import router as discovery_router
    from app.workflow.router import router as workflow_router
    from app.knowledge.router import router as knowledge_router
    from app.crm.inbox_router import router as inbox_router

    app.include_router(platform_router)
    app.include_router(discovery_router)
    app.include_router(workflow_router)
    app.include_router(knowledge_router)
    app.include_router(inbox_router)

    return app


app = create_app()
