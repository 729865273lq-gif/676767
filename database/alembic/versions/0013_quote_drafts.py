"""Add quote drafts for manual quotation workflow.

Revision ID: 0013_quote_drafts
Revises: 0012_follow_up_tasks
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_quote_drafts"
down_revision = "0012_follow_up_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("sent_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("currency", sa.String(length=10), server_default="USD", nullable=False),
        sa.Column("incoterm", sa.String(length=20), server_default="FOB", nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("line_items", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(length=2000), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sent_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quote_drafts_created_by_user_id", "quote_drafts", ["created_by_user_id"])
    op.create_index("ix_quote_drafts_lead_id", "quote_drafts", ["lead_id"])
    op.create_index("ix_quote_drafts_organization_id", "quote_drafts", ["organization_id"])
    op.create_index("ix_quote_drafts_product_line_id", "quote_drafts", ["product_line_id"])
    op.create_index("ix_quote_drafts_sent_by_user_id", "quote_drafts", ["sent_by_user_id"])
    op.create_index("ix_quote_drafts_status", "quote_drafts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_quote_drafts_status", table_name="quote_drafts")
    op.drop_index("ix_quote_drafts_sent_by_user_id", table_name="quote_drafts")
    op.drop_index("ix_quote_drafts_product_line_id", table_name="quote_drafts")
    op.drop_index("ix_quote_drafts_organization_id", table_name="quote_drafts")
    op.drop_index("ix_quote_drafts_lead_id", table_name="quote_drafts")
    op.drop_index("ix_quote_drafts_created_by_user_id", table_name="quote_drafts")
    op.drop_table("quote_drafts")
