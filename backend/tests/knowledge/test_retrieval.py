from __future__ import annotations

import asyncio

from app.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
from app.knowledge.retrieval import RetrievalService
from app.knowledge.vector_store import InMemoryVectorStore, VectorChunk
from app.platform.models import ProductLine


class FakeEmbeddingConnector:
    connector_id = "fake-embedding"
    version = "v1"

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [self.mapping[text] for text in texts]


def upsert(vector_store, record):
    asyncio.run(vector_store.upsert(record))


def add_chunk(session, *, organization_id, document, text, chunk_index=0):
    chunk = KnowledgeChunk(
        document_id=document.id,
        organization_id=organization_id,
        chunk_index=chunk_index,
        content=text,
        token_estimate=max(1, len(text) // 4),
        page_or_sheet="page 1",
        excerpt=text[:200],
    )
    session.add(chunk)
    session.flush()
    return chunk


def ready_document(session, *, organization_id, filename, product_line_id=None):
    document = KnowledgeDocument(
        organization_id=organization_id,
        filename=filename,
        content_type="application/pdf",
        size=10,
        status=KnowledgeDocumentStatus.READY,
        product_line_id=product_line_id,
    )
    session.add(document)
    session.flush()
    return document


def test_search_returns_only_requesting_organizations_chunks(session, organizations):
    vector_store = InMemoryVectorStore()
    embedding = FakeEmbeddingConnector({"question": [1.0, 0.0, 0.0]})

    acme_doc = ready_document(session, organization_id=organizations["acme"].id, filename="acme.pdf")
    globex_doc = ready_document(session, organization_id=organizations["globex"].id, filename="globex.pdf")
    acme_chunk = add_chunk(
        session, organization_id=organizations["acme"].id, document=acme_doc, text="acme secret"
    )
    globex_chunk = add_chunk(
        session, organization_id=organizations["globex"].id, document=globex_doc, text="globex secret"
    )
    session.commit()

    upsert(
        vector_store,
        VectorChunk(
            chunk_id=acme_chunk.id,
            organization_id=organizations["acme"].id,
            document_id=acme_doc.id,
            product_line_id=None,
            embedding=[1.0, 0.0, 0.0],
        ),
    )
    upsert(
        vector_store,
        VectorChunk(
            chunk_id=globex_chunk.id,
            organization_id=organizations["globex"].id,
            document_id=globex_doc.id,
            product_line_id=None,
            embedding=[1.0, 0.0, 0.0],
        ),
    )

    results = asyncio.run(RetrievalService(session, embedding, vector_store).search(organizations["acme"].id, "question"))

    assert len(results) == 1
    assert results[0].document_id == acme_doc.id
    assert results[0].document_filename == "acme.pdf"
    assert results[0].content == "acme secret"
    assert results[0].page_or_sheet == "page 1"
    assert results[0].excerpt == "acme secret"
    assert results[0].similarity > 0.99


def test_search_filters_by_product_line(session, organizations):
    vector_store = InMemoryVectorStore()
    embedding = FakeEmbeddingConnector({"question": [1.0, 0.0, 0.0]})
    lighting = ProductLine(organization_id=organizations["acme"].id, name="Lighting")
    bearings = ProductLine(organization_id=organizations["acme"].id, name="Bearings")
    session.add_all([lighting, bearings])
    session.flush()

    lighting_doc = ready_document(
        session,
        organization_id=organizations["acme"].id,
        filename="lighting.pdf",
        product_line_id=lighting.id,
    )
    bearings_doc = ready_document(
        session,
        organization_id=organizations["acme"].id,
        filename="bearings.pdf",
        product_line_id=bearings.id,
    )
    lighting_chunk = add_chunk(
        session, organization_id=organizations["acme"].id, document=lighting_doc, text="lighting text"
    )
    bearings_chunk = add_chunk(
        session, organization_id=organizations["acme"].id, document=bearings_doc, text="bearings text"
    )
    session.commit()

    upsert(
        vector_store,
        VectorChunk(
            chunk_id=lighting_chunk.id,
            organization_id=organizations["acme"].id,
            document_id=lighting_doc.id,
            product_line_id=lighting.id,
            embedding=[1.0, 0.0, 0.0],
        ),
    )
    upsert(
        vector_store,
        VectorChunk(
            chunk_id=bearings_chunk.id,
            organization_id=organizations["acme"].id,
            document_id=bearings_doc.id,
            product_line_id=bearings.id,
            embedding=[1.0, 0.0, 0.0],
        ),
    )

    results = asyncio.run(
        RetrievalService(session, embedding, vector_store).search(
            organizations["acme"].id, "question", product_line_id=lighting.id
        )
    )

    assert len(results) == 1
    assert results[0].document_id == lighting_doc.id
