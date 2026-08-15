"""Add product-line exclusions for customer discovery.

Revision ID: 0020_product_line_exclusions
Revises: 0019_lead_last_discovered_at
Create Date: 2026-08-13 12:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_product_line_exclusions"
down_revision: str | None = "0019_lead_last_discovered_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_lines",
        sa.Column("excluded_keywords", sa.JSON(), nullable=False, server_default="[]"),
    )
    with op.batch_alter_table("product_lines") as batch_op:
        batch_op.alter_column(
            "excluded_keywords",
            existing_type=sa.JSON(),
            server_default=None,
        )


def downgrade() -> None:
    op.drop_column("product_lines", "excluded_keywords")
