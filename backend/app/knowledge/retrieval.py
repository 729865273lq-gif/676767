from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus


@dataclass
class RetrievalResult:
    document_id: str
    document_filename: str
    content: str
    page_or_sheet: str
    excerpt: str
    similarity: float


class RetrievalService:
    def __init__(self, session: Session, embedding_connector, vector_store) -> None:
        self.session = session
        self.embedding = embedding_connector
        self.vector_store = vector_store

    async def search(
        self,
        organization_id: str,
        query: str,
        limit: int = 5,
        product_line_id: str | None = None,
    ) -> list[RetrievalResult]:
        embeddings = await self.embedding.embed([query])
        query_embedding = embeddings[0] if embeddings else []
        matches = await self.vector_store.search(
            query_embedding,
            organization_id,
            limit=limit,
            product_line_id=product_line_id,
        )
        results: list[RetrievalResult] = []
        for match in matches:
            if match.document_filename and match.content:
                # The pgvector store already joined the chunk/document and filtered by
                # organization + ready status in SQL, so no extra per-match lookups are needed.
                results.append(
                    RetrievalResult(
                        document_id=match.document_id,
                        document_filename=match.document_filename,
                        content=match.content,
                        page_or_sheet=match.page_or_sheet,
                        excerpt=match.excerpt,
                        similarity=match.similarity,
                    )
                )
                continue
            # In-memory store: fill fields and enforce scope/status via the session.
            chunk = self.session.get(KnowledgeChunk, match.chunk_id)
            if chunk is None or chunk.organization_id != organization_id:
                continue
            document = self.session.get(KnowledgeDocument, chunk.document_id)
            if document is None or document.organization_id != organization_id:
                continue
            if document.status != KnowledgeDocumentStatus.READY:
                continue
            results.append(
                RetrievalResult(
                    document_id=document.id,
                    document_filename=document.filename,
                    content=chunk.content,
                    page_or_sheet=chunk.page_or_sheet,
                    excerpt=chunk.excerpt,
                    similarity=match.similarity,
                )
            )
        return results[:limit]
