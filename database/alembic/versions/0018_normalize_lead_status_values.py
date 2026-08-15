"""Normalize legacy lead status values.

Revision ID: 0018_normalize_lead_status
Revises: 0017_contact_social_profiles
Create Date: 2026-08-11 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_normalize_lead_status"
down_revision: str | None = "0017_contact_social_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE leads
        SET status = upper(status)
        WHERE status IN (
            'new', 'to_contact', 'contacted', 'interested',
            'quoting', 'won', 'not_fit'
        )
        """
    )
    with op.batch_alter_table("leads") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=30),
            server_default="NEW",
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute(
        """
        UPDATE leads
        SET status = lower(status)
        WHERE status IN (
            'NEW', 'TO_CONTACT', 'CONTACTED', 'INTERESTED',
            'QUOTING', 'WON', 'NOT_FIT'
        )
        """
    )
    with op.batch_alter_table("leads") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=30),
            server_default="new",
            existing_nullable=False,
        )
