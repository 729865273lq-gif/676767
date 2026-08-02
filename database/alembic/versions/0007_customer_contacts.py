"""Add CRM contacts for customer detail.

Revision ID: 0007_customer_contacts
Revises: 0006_customer_detail_followups
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_customer_contacts"
down_revision = "0006_customer_detail_followups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_contacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("linkedin_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("whatsapp", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_contacts_lead_id", "crm_contacts", ["lead_id"])
    op.create_index("ix_crm_contacts_organization_id", "crm_contacts", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_crm_contacts_organization_id", table_name="crm_contacts")
    op.drop_index("ix_crm_contacts_lead_id", table_name="crm_contacts")
    op.drop_table("crm_contacts")
