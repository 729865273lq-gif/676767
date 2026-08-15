from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
from app.knowledge.vector_store import EMBEDDING_DIM, PgVectorStore, VectorChunk
from app.platform.models import Organization

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL and DATABASE_URL not set; pgvector integration test skipped",
        allow_module_level=True,
    )


def _embedding(seed: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[seed % EMBEDDING_DIM] = 1.0
    return vector


def test_pgvector_search_handles_null_product_line_filter() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    organization = Organization(name=f"smoke-it-{uuid.uuid4().hex[:8]}")
    session.add(organization)
    session.flush()

    document = KnowledgeDocument(
        organization_id=organization.id,
        filename="smoke-it.pdf",
        content_type="application/pdf",
        size=1,
        status=KnowledgeDocumentStatus.READY,
    )
    session.add(document)
    session.flush()

    chunk = KnowledgeChunk(
        document_id=document.id,
        organization_id=organization.id,
        chunk_index=0,
        content="smoke-it bearings",
        token_estimate=1,
        page_or_sheet="page 1",
        excerpt="smoke-it bearings",
    )
    session.add(chunk)
    session.flush()

    chunk_id = chunk.id
    document_id = document.id
    organization_id = organization.id
    store = PgVectorStore(session)

    try:
        asyncio.run(
            store.upsert(
                VectorChunk(
                    chunk_id=chunk.id,
                    organization_id=organization.id,
                    document_id=document.id,
                    product_line_id=None,
                    embedding=_embedding(7),
                )
            )
        )

        hits = asyncio.run(store.search(_embedding(7), organization.id, limit=5))
        assert [hit.chunk_id for hit in hits] == [chunk.id]

        empty = asyncio.run(
            store.search(_embedding(7), organization.id, limit=5, product_line_id="0" * 36)
        )
        assert empty == []
    finally:
        session.rollback()
        session.execute(
            text("DELETE FROM knowledge_vectors WHERE chunk_id = :chunk_id"),
            {"chunk_id": chunk_id},
        )
        persisted_chunk = session.get(KnowledgeChunk, chunk_id)
        persisted_document = session.get(KnowledgeDocument, document_id)
        persisted_organization = session.get(Organization, organization_id)
        if persisted_chunk is not None:
            session.delete(persisted_chunk)
        if persisted_document is not None:
            session.delete(persisted_document)
        if persisted_organization is not None:
            session.delete(persisted_organization)
        session.commit()
        session.close()
