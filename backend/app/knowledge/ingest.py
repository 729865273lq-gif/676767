from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from app.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentStatus
from app.knowledge.vector_store import VectorChunk

CHUNK_TOKENS = 512
OVERLAP_TOKENS = 64
CHARS_PER_TOKEN = 4
EXCERPT_CHARS = 200

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class EmbeddingNotConfiguredError(RuntimeError):
    """Raised when ingestion has no embedding connector to encode chunks."""


@dataclass
class ParsedSection:
    text: str
    page_or_sheet: str = ""


@dataclass
class ChunkDraft:
    content: str
    token_estimate: int
    page_or_sheet: str
    excerpt: str


def parse_pdf(content: bytes) -> list[ParsedSection]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    sections: list[ParsedSection] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(ParsedSection(text=text, page_or_sheet=f"page {index}"))
    return sections


def parse_docx(content: bytes) -> list[ParsedSection]:
    from docx import Document

    document = Document(BytesIO(content))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
    text = "\n".join(paragraph for paragraph in paragraphs if paragraph)
    if not text:
        return []
    return [ParsedSection(text=text, page_or_sheet="")]


def parse_xlsx(content: bytes) -> list[ParsedSection]:
    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    sections: list[ParsedSection] = []
    for sheet in workbook.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
            if cells:
                rows.append(" | ".join(cells))
        text = "\n".join(rows)
        if text:
            sections.append(ParsedSection(text=text, page_or_sheet=sheet.title))
    return sections


CONTENT_TYPE_PARSERS = {
    PDF_CONTENT_TYPE: parse_pdf,
    DOCX_CONTENT_TYPE: parse_docx,
    XLSX_CONTENT_TYPE: parse_xlsx,
}


def chunk_sections(
    sections: list[ParsedSection],
    chunk_size: int = CHUNK_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> list[ChunkDraft]:
    chunk_chars = max(1, chunk_size * CHARS_PER_TOKEN)
    overlap_chars = max(0, overlap * CHARS_PER_TOKEN)
    chunks: list[ChunkDraft] = []
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            piece = text[start : start + chunk_chars]
            chunks.append(
                ChunkDraft(
                    content=piece,
                    token_estimate=max(1, len(piece) // CHARS_PER_TOKEN),
                    page_or_sheet=section.page_or_sheet,
                    excerpt=piece[:EXCERPT_CHARS],
                )
            )
            if start + chunk_chars >= len(text):
                break
            start += chunk_chars - overlap_chars
    return chunks


class IngestionService:
    def __init__(self, session, *, storage, embedding=None, vector_store=None) -> None:
        self.session = session
        self.storage = storage
        self.embedding = embedding
        self.vector_store = vector_store

    def create_document(
        self,
        *,
        organization_id: str,
        filename: str,
        content_type: str,
        size: int,
        product_line_id: str | None = None,
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            organization_id=organization_id,
            filename=filename,
            content_type=content_type,
            size=size,
            product_line_id=product_line_id,
        )
        self.session.add(document)
        self.session.flush()
        return document

    async def process(self, document_id: str, organization_id: str, content: bytes) -> KnowledgeDocument:
        document = self.session.get(KnowledgeDocument, document_id)
        if document is None or document.organization_id != organization_id:
            raise LookupError("knowledge document not found")
        document.status = KnowledgeDocumentStatus.PROCESSING
        document.failure_message = ""
        self.session.commit()
        try:
            await self._ingest(document, content)
        except Exception as error:
            self.session.rollback()
            document = self.session.get(KnowledgeDocument, document_id)
            document.status = KnowledgeDocumentStatus.FAILED
            document.failure_message = str(error)
            self.session.commit()
        return document

    async def _ingest(self, document: KnowledgeDocument, content: bytes) -> None:
        parser = CONTENT_TYPE_PARSERS.get(document.content_type)
        if parser is None:
            raise ValueError(f"unsupported content type: {document.content_type}")
        if self.embedding is None:
            raise EmbeddingNotConfiguredError(
                "embedding is not configured; set EMBEDDING_API_KEY before ingesting documents"
            )
        sections = parser(content)
        chunks = chunk_sections(sections)
        texts = [chunk.content for chunk in chunks]
        embeddings = await self.embedding.embed(texts) if texts else []

        key = f"{document.organization_id}/{document.id}/{document.filename}"
        await self.storage.put(key, content)

        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            persisted = KnowledgeChunk(
                document_id=document.id,
                organization_id=document.organization_id,
                chunk_index=index,
                content=chunk.content,
                token_estimate=chunk.token_estimate,
                page_or_sheet=chunk.page_or_sheet,
                excerpt=chunk.excerpt,
            )
            self.session.add(persisted)
            self.session.flush()
            if self.vector_store is not None:
                await self.vector_store.upsert(
                    VectorChunk(
                        chunk_id=persisted.id,
                        organization_id=document.organization_id,
                        document_id=document.id,
                        product_line_id=document.product_line_id,
                        embedding=embedding,
                    )
                )
        document.status = KnowledgeDocumentStatus.READY
        document.failure_message = ""
        self.session.commit()
