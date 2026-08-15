"""Track provider message ids for sent email drafts.

Revision ID: 0014_email_provider_message_id
Revises: 0013_quote_drafts
Create Date: 2026-08-09 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_email_provider_message_id"
down_revision: str | None = "0013_quote_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_drafts",
        sa.Column("provider_message_id", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("email_drafts", "provider_message_id")
