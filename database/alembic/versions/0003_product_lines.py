"""Create configurable product lines and suppliers.

Revision ID: 0003_product_lines
Revises: 0002_workflow
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_product_lines"
down_revision = "0002_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("product_keywords", sa.JSON(), nullable=False),
        sa.Column("buyer_profiles", sa.JSON(), nullable=False),
        sa.Column("target_regions", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_product_line_name"),
    )
    op.create_index("ix_product_lines_organization_id", "product_lines", ["organization_id"])
    op.create_table(
        "product_suppliers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_line_id", "name", name="uq_supplier_name"),
    )
    op.create_index("ix_product_suppliers_organization_id", "product_suppliers", ["organization_id"])
    op.create_index("ix_product_suppliers_product_line_id", "product_suppliers", ["product_line_id"])


def downgrade() -> None:
    op.drop_index("ix_product_suppliers_product_line_id", table_name="product_suppliers")
    op.drop_index("ix_product_suppliers_organization_id", table_name="product_suppliers")
    op.drop_table("product_suppliers")
    op.drop_index("ix_product_lines_organization_id", table_name="product_lines")
    op.drop_table("product_lines")
