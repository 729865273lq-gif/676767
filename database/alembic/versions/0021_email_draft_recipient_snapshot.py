"""Add immutable recipient snapshots to email drafts.

Revision ID: 0021_email_recipient_snapshot
Revises: 0020_product_line_exclusions
Create Date: 2026-08-13 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_email_recipient_snapshot"
down_revision: str | None = "0020_product_line_exclusions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_drafts",
        sa.Column("recipient_email", sa.String(length=320), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE email_drafts
        SET recipient_email = crm_contacts.email
        FROM crm_contacts
        WHERE email_drafts.contact_id = crm_contacts.id
          AND email_drafts.recipient_email = ''
        """
    )
    with op.batch_alter_table("email_drafts") as batch_op:
        batch_op.alter_column(
            "recipient_email",
            existing_type=sa.String(length=320),
            server_default=None,
        )


def downgrade() -> None:
    op.drop_column("email_drafts", "recipient_email")
