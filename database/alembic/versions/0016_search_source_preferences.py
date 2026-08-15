"""Add organization search source preferences.

Revision ID: 0016_search_source_preferences
Revises: 0015_contact_email_verification
Create Date: 2026-08-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_search_source_preferences"
down_revision: str | None = "0015_contact_email_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_source_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "source_id", name="uq_search_source_preference"),
    )
    op.create_index(
        op.f("ix_search_source_preferences_organization_id"),
        "search_source_preferences",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_search_source_preferences_organization_id"), table_name="search_source_preferences")
    op.drop_table("search_source_preferences")
