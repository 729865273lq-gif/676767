from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.knowledge.models import KnowledgeDocumentStatus

# Embedding dimension produced by the configured embedding model. The pgvector
# column in the ``knowledge_vectors`` table is declared with this dimension.
EMBEDDING_DIM = 1024


@dataclass
class VectorChunk:
    chunk_id: str
    organization_id: str
    document_id: str
    product_line_id: str | None
    embedding: list[float]


@dataclass
class VectorMatch:
    chunk_id: str
    document_id: str
    similarity: float
    content: str = ""
    document_filename: str = ""
    page_or_sheet: str = ""
    excerpt: str = ""


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class InMemoryVectorStore:
    connector_id = "in-memory-vector"
    version = "v1"

    def __init__(self) -> None:
        self._records: dict[str, VectorChunk] = {}

    async def upsert(self, record: VectorChunk) -> None:
        self._records[record.chunk_id] = record

    async def search(
        self,
        query_embedding: list[float],
        organization_id: str,
        limit: int = 5,
        product_line_id: str | None = None,
    ) -> list[VectorMatch]:
        candidates = [
            record
            for record in self._records.values()
            if record.organization_id == organization_id
            and (product_line_id is None or record.product_line_id == product_line_id)
        ]
        scored = [(record, _cosine_similarity(query_embedding, record.embedding)) for record in candidates]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            VectorMatch(chunk_id=record.chunk_id, document_id=record.document_id, similarity=similarity)
            for record, similarity in scored[:limit]
        ]


class PgVectorStore:
    connector_id = "pg-vector"
    version = "v1"

    def __init__(self, session: Session) -> None:
        self._session = session

    async def upsert(self, record: VectorChunk) -> None:
        if len(record.embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"embedding dimension mismatch: got {len(record.embedding)}, expected {EMBEDDING_DIM}; "
                "verify EMBEDDING_MODEL matches the knowledge_vectors column dimension"
            )
        # The caller (IngestionService) owns the transaction and commits once at the end.
        self._session.execute(
            text(
                """
                INSERT INTO knowledge_vectors (chunk_id, organization_id, embedding)
                VALUES (:chunk_id, :organization_id, CAST(:embedding AS vector))
                ON CONFLICT (chunk_id) DO UPDATE SET
                    organization_id = EXCLUDED.organization_id,
                    embedding = EXCLUDED.embedding
                """
            ),
            {
                "chunk_id": record.chunk_id,
                "organization_id": record.organization_id,
                "embedding": _vector_literal(record.embedding),
            },
        )

    async def search(
        self,
        query_embedding: list[float],
        organization_id: str,
        limit: int = 5,
        product_line_id: str | None = None,
    ) -> list[VectorMatch]:
        params: dict[str, object] = {
            "query": _vector_literal(query_embedding),
            "organization_id": organization_id,
            "ready_status": KnowledgeDocumentStatus.READY.name,
            "limit": limit,
        }
        product_line_clause = ""
        if product_line_id is not None:
            product_line_clause = "AND document.product_line_id = :product_line_id"
            params["product_line_id"] = product_line_id
        rows = self._session.execute(
            text(
                f"""
                SELECT vector.chunk_id, chunk.document_id,
                       chunk.content, document.filename AS document_filename,
                       chunk.page_or_sheet, chunk.excerpt,
                       1 - (vector.embedding <=> CAST(:query AS vector)) AS similarity
                FROM knowledge_vectors vector
                JOIN knowledge_chunks chunk ON chunk.id = vector.chunk_id
                JOIN knowledge_documents document ON document.id = chunk.document_id
                WHERE document.organization_id = :organization_id
                  AND document.status = :ready_status
                  {product_line_clause}
                ORDER BY vector.embedding <=> CAST(:query AS vector)
                LIMIT :limit
                """
            ),
            params,
        )
        return [
            VectorMatch(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                content=row.content,
                document_filename=row.document_filename,
                page_or_sheet=row.page_or_sheet,
                excerpt=row.excerpt,
                similarity=row.similarity,
            )
            for row in rows
        ]


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(value) for value in embedding) + "]"
