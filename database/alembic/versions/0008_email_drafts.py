"""Add email drafts and approval state.

Revision ID: 0008_email_drafts
Revises: 0007_customer_contacts
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_email_drafts"
down_revision = "0007_customer_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_approval"),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.String(length=8000), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("rejection_reason", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["contact_id"], ["crm_contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_drafts_contact_id", "email_drafts", ["contact_id"])
    op.create_index("ix_email_drafts_created_by_user_id", "email_drafts", ["created_by_user_id"])
    op.create_index("ix_email_drafts_lead_id", "email_drafts", ["lead_id"])
    op.create_index("ix_email_drafts_organization_id", "email_drafts", ["organization_id"])
    op.create_index("ix_email_drafts_product_line_id", "email_drafts", ["product_line_id"])
    op.create_index("ix_email_drafts_reviewed_by_user_id", "email_drafts", ["reviewed_by_user_id"])
    op.create_index("ix_email_drafts_status", "email_drafts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_email_drafts_status", table_name="email_drafts")
    op.drop_index("ix_email_drafts_reviewed_by_user_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_product_line_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_organization_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_lead_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_created_by_user_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_contact_id", table_name="email_drafts")
    op.drop_table("email_drafts")
