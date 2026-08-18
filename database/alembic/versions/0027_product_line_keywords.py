"""Add multilingual search keyword translations for product lines.

Revision ID: 0027_product_line_keywords
Revises: 0026_inbox_lead
Create Date: 2026-08-16 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_product_line_keywords"
down_revision: str | None = "0026_inbox_lead"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_line_search_keywords",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("auto", "manual", name="keywordsource", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_line_id", "language", name="uq_product_line_search_keyword_language"
        ),
    )
    op.create_index(
        "ix_product_line_search_keywords_product_line_id",
        "product_line_search_keywords",
        ["product_line_id"],
    )
    op.create_index(
        "ix_product_line_search_keywords_organization_id",
        "product_line_search_keywords",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_line_search_keywords_organization_id",
        table_name="product_line_search_keywords",
    )
    op.drop_index(
        "ix_product_line_search_keywords_product_line_id",
        table_name="product_line_search_keywords",
    )
    op.drop_table("product_line_search_keywords")
