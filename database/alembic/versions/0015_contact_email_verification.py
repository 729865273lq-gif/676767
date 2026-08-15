"""Track contact email verification results.

Revision ID: 0015_contact_email_verification
Revises: 0014_email_provider_message_id
Create Date: 2026-08-09 10:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_contact_email_verification"
down_revision: str | None = "0014_email_provider_message_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_contacts",
        sa.Column("email_verification_provider", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "crm_contacts",
        sa.Column("email_verification_status", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "crm_contacts",
        sa.Column("email_verification_sub_status", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column("crm_contacts", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("crm_contacts", "email_verified_at")
    op.drop_column("crm_contacts", "email_verification_sub_status")
    op.drop_column("crm_contacts", "email_verification_status")
    op.drop_column("crm_contacts", "email_verification_provider")
