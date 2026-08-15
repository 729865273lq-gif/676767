"""Add flexible social profiles and source URL to CRM contacts.

Revision ID: 0017_contact_social_profiles
Revises: 0016_search_source_preferences
Create Date: 2026-08-11 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_contact_social_profiles"
down_revision: str | None = "0016_search_source_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_contacts",
        sa.Column("social_profiles", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "crm_contacts",
        sa.Column("source_url", sa.String(length=1_000), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("crm_contacts", "source_url")
    op.drop_column("crm_contacts", "social_profiles")
