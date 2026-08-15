from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.connectors.llm import EmbeddingConfigurationError, OpenAICompatibleEmbeddingConnector
from app.connectors.storage import S3StorageConnector
from app.knowledge.ingest import IngestionService
from app.knowledge.models import KnowledgeDocument
from app.knowledge.retrieval import RetrievalService
from app.knowledge.service import KnowledgeService
from app.knowledge.vector_store import PgVectorStore
from app.platform.models import MembershipRole
from app.platform.product_lines import ProductLineNotFound, ProductLineService
from app.platform.router import current_principal, get_session
from app.platform.service import OrganizationService, TenantAccessDenied
from app.shared.security import SignedPrincipal

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024


def _require_admin(principal: SignedPrincipal, organization_id: str, session: Session) -> None:
    try:
        OrganizationService(session).require_admin(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error


def _require_membership(principal: SignedPrincipal, organization_id: str, session: Session) -> MembershipRole:
    try:
        membership = OrganizationService(session).require_membership(principal.user_id, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return membership.role


def _embedding_connector(request: Request):
    injected = getattr(request.app.state, "embedding_connector", None)
    if injected is not None:
        return injected
    try:
        return OpenAICompatibleEmbeddingConnector.from_settings(request.app.state.settings)
    except EmbeddingConfigurationError:
        return None


def _storage_connector(request: Request):
    injected = getattr(request.app.state, "storage_connector", None)
    if injected is not None:
        return injected
    return S3StorageConnector.from_settings(request.app.state.settings)


def _vector_store(request: Request, session: Session):
    injected = getattr(request.app.state, "vector_store", None)
    if injected is not None:
        return injected
    return PgVectorStore(session)


def document_response(document: KnowledgeDocument, *, is_admin: bool) -> dict[str, object]:
    response: dict[str, object] = {
        "id": document.id,
        "filename": document.filename,
        "content_type": document.content_type,
        "size": document.size,
        "status": document.status.value,
        "product_line_id": document.product_line_id,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }
    if is_admin:
        response["failure_message"] = document.failure_message
    return response


@router.post(
    "/organizations/{organization_id}/documents",
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    organization_id: str,
    request: Request,
    file: UploadFile = File(...),
    product_line_id: str | None = Form(default=None),
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _require_admin(principal, organization_id, session)
    normalized_product_line_id = (product_line_id or "").strip() or None
    if normalized_product_line_id is not None:
        try:
            ProductLineService(session).get_product_line(normalized_product_line_id, organization_id)
        except ProductLineNotFound as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    # Reject oversized uploads from the declared Content-Length before reading the body.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="file exceeds the 25 MB upload limit",
            )

    content = await file.read()
    # Guard against a missing or understated Content-Length as well.
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="file exceeds the 25 MB upload limit",
        )
    filename = (file.filename or "document").strip()
    content_type = (file.content_type or "").strip() or "application/octet-stream"
    service = IngestionService(
        session,
        storage=_storage_connector(request),
        embedding=_embedding_connector(request),
        vector_store=_vector_store(request, session),
    )
    document = service.create_document(
        organization_id=organization_id,
        filename=filename,
        content_type=content_type,
        size=len(content),
        product_line_id=normalized_product_line_id,
    )
    document = await service.process(document.id, organization_id, content)
    return document_response(document, is_admin=True)


@router.get("/organizations/{organization_id}/documents")
def list_documents(
    organization_id: str,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    role = _require_membership(principal, organization_id, session)
    documents = KnowledgeService(session).list_documents(organization_id)
    return [
        document_response(document, is_admin=role == MembershipRole.ADMIN) for document in documents
    ]


@router.get("/organizations/{organization_id}/search")
async def search_documents(
    organization_id: str,
    query: str,
    request: Request,
    limit: int = Query(default=5, ge=1, le=50),
    product_line_id: str | None = None,
    principal: SignedPrincipal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    _require_membership(principal, organization_id, session)
    normalized_product_line_id = (product_line_id or "").strip() or None
    if normalized_product_line_id is not None:
        try:
            ProductLineService(session).get_product_line(normalized_product_line_id, organization_id)
        except ProductLineNotFound as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    embedding = _embedding_connector(request)
    if embedding is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="embedding provider is not configured",
        )
    results = await RetrievalService(session, embedding, _vector_store(request, session)).search(
        organization_id,
        query,
        limit=limit,
        product_line_id=normalized_product_line_id,
    )
    return [
        {
            "document_id": result.document_id,
            "document_filename": result.document_filename,
            "content": result.content,
            "page_or_sheet": result.page_or_sheet,
            "excerpt": result.excerpt,
            "similarity": result.similarity,
        }
        for result in results
    ]
