"""Add website inquiry intake.

Revision ID: 0010_website_inquiries
Revises: 0009_email_sent_state
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_website_inquiries"
down_revision = "0009_email_sent_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_inquiries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("company_name", sa.String(length=300), nullable=False),
        sa.Column("contact_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("website", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("target_market", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("message", sa.String(length=4000), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_website_inquiries_lead_id", "website_inquiries", ["lead_id"])
    op.create_index("ix_website_inquiries_organization_id", "website_inquiries", ["organization_id"])
    op.create_index("ix_website_inquiries_product_line_id", "website_inquiries", ["product_line_id"])
    op.create_index("ix_website_inquiries_status", "website_inquiries", ["status"])


def downgrade() -> None:
    op.drop_index("ix_website_inquiries_status", table_name="website_inquiries")
    op.drop_index("ix_website_inquiries_product_line_id", table_name="website_inquiries")
    op.drop_index("ix_website_inquiries_organization_id", table_name="website_inquiries")
    op.drop_index("ix_website_inquiries_lead_id", table_name="website_inquiries")
    op.drop_table("website_inquiries")
