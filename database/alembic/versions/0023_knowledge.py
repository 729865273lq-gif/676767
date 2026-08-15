"""Add organization knowledge base documents, chunks and vector index.

Revision ID: 0023_knowledge
Revises: 0022_lead_contact_status
Create Date: 2026-08-14 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_knowledge"
down_revision: str | None = "0022_lead_contact_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        # Mirror of app.knowledge.models.KnowledgeDocumentStatus (StrEnum). The ORM maps this
        # column with Enum(StrEnum, native_enum=False), which persists the member NAME (e.g. READY).
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "processing",
                "ready",
                "failed",
                name="knowledgedocumentstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("failure_message", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("product_line_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_organization_id", "knowledge_documents", ["organization_id"]
    )
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_index(
        "ix_knowledge_documents_product_line_id", "knowledge_documents", ["product_line_id"]
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("page_or_sheet", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("excerpt", sa.String(length=500), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index(
        "ix_knowledge_chunks_organization_id", "knowledge_chunks", ["organization_id"]
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # The vector(1024) dimension below must match app.knowledge.vector_store.EMBEDDING_DIM.
        op.execute(
            """
            CREATE TABLE knowledge_vectors (
                chunk_id VARCHAR(36) PRIMARY KEY,
                organization_id VARCHAR(36) NOT NULL,
                embedding vector(1024) NOT NULL
            )
            """
        )
        op.execute(
            "CREATE INDEX ix_knowledge_vectors_organization_id "
            "ON knowledge_vectors (organization_id)"
        )
        op.execute(
            "CREATE INDEX ix_knowledge_vectors_embedding "
            "ON knowledge_vectors USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_vectors_embedding")
        op.execute("DROP INDEX IF EXISTS ix_knowledge_vectors_organization_id")
        op.execute("DROP TABLE IF EXISTS knowledge_vectors")
    op.drop_index("ix_knowledge_chunks_organization_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_product_line_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_organization_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
