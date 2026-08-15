"""Track bulk contact discovery status on customer leads.

Revision ID: 0022_lead_contact_status
Revises: 0021_email_recipient_snapshot
Create Date: 2026-08-13 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_lead_contact_status"
down_revision: str | None = "0021_email_recipient_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("contact_discovery_status", sa.String(length=30), nullable=False, server_default="not_scanned"),
    )
    op.add_column(
        "leads",
        sa.Column("contact_discovery_message", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column("leads", sa.Column("contact_discovered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "leads", sa.Column("contact_email_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "leads", sa.Column("contact_phone_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "leads", sa.Column("contact_social_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_index(
        "ix_leads_contact_discovery_status", "leads", ["contact_discovery_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_leads_contact_discovery_status", table_name="leads")
    op.drop_column("leads", "contact_social_count")
    op.drop_column("leads", "contact_phone_count")
    op.drop_column("leads", "contact_email_count")
    op.drop_column("leads", "contact_discovered_at")
    op.drop_column("leads", "contact_discovery_message")
    op.drop_column("leads", "contact_discovery_status")
